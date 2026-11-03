"""Build VCALENDAR and VEVENT logical content lines."""

from collections.abc import Iterable
from datetime import UTC, datetime

from panorama_calendar.ics.alarm import build_alarm_lines
from panorama_calendar.ics.escape import escape_text
from panorama_calendar.models.event import EventRecord

DEFAULT_PRODID = "-//Personal Panorama Calendar//ICS Core 1.0//CN"

#: How often clients should re-poll the feed. Matches the cloud build cadence
#: (every six hours); Apple Calendar and others honour these hints when
#: deciding when to fetch instead of relying on their own heuristics.
DEFAULT_REFRESH_INTERVAL = "PT6H"


def _format_utc(value: datetime) -> str:
    """Format an aware datetime as an RFC 5545 UTC timestamp."""
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _event_sort_key(event: EventRecord) -> tuple[str, str]:
    """Provide deterministic output ordering across runs."""
    if event.start_date is not None:
        return event.start_date.isoformat(), event.uid or ""
    if event.start_at_utc is not None:
        return event.start_at_utc.isoformat(), event.uid or ""
    return "", event.uid or ""


def build_event_lines(event: EventRecord) -> list[str]:
    """Serialize one unified event into unfolded VEVENT lines."""
    if not event.uid:
        raise ValueError("event UID must be initialized")

    lines = ["BEGIN:VEVENT", f"UID:{event.uid}", f"DTSTAMP:{_format_utc(event.dtstamp)}"]
    if event.start_date is not None and event.end_date_exclusive is not None:
        lines.append(f"DTSTART;VALUE=DATE:{event.start_date.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{event.end_date_exclusive.strftime('%Y%m%d')}")
    elif event.start_at_utc is not None:
        lines.append(f"DTSTART:{_format_utc(event.start_at_utc)}")
        if event.end_at_utc is not None:
            lines.append(f"DTEND:{_format_utc(event.end_at_utc)}")

    lines.extend(
        [
            f"SUMMARY:{escape_text(event.summary)}",
            f"DESCRIPTION:{escape_text(event.description)}",
            f"STATUS:{event.status.value}",
            f"SEQUENCE:{event.sequence}",
            f"TRANSP:{'TRANSPARENT' if event.transparent else 'OPAQUE'}",
        ]
    )
    if event.location:
        lines.append(f"LOCATION:{escape_text(event.location)}")
    if event.sources:
        # URL is a first-class property: clients render it as a tappable link,
        # which a long URL folded inside DESCRIPTION cannot provide.
        lines.append(f"URL:{event.sources[0].url}")
    if event.last_modified is not None:
        lines.append(f"LAST-MODIFIED:{_format_utc(event.last_modified)}")
    if event.categories:
        lines.append(f"CATEGORIES:{','.join(escape_text(item) for item in event.categories)}")
    if event.end_estimated:
        lines.append("X-PANORAMA-END-ESTIMATED:TRUE")
    for alarm in event.alarms:
        lines.extend(build_alarm_lines(alarm))
    lines.append("END:VEVENT")
    return lines


def build_calendar_lines(
    events: Iterable[EventRecord],
    calendar_name: str,
    prodid: str = DEFAULT_PRODID,
    refresh_interval: str = DEFAULT_REFRESH_INTERVAL,
) -> list[str]:
    """Build one VCALENDAR with deterministic event ordering."""
    if "\r" in prodid or "\n" in prodid:
        raise ValueError("PRODID must be single-line")
    if not refresh_interval or "\r" in refresh_interval or "\n" in refresh_interval:
        raise ValueError("refresh interval must be a single-line ISO 8601 duration")
    lines = [
        "BEGIN:VCALENDAR",
        f"PRODID:{prodid}",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(calendar_name)}",
        f"X-PUBLISHED-TTL:{refresh_interval}",
        f"REFRESH-INTERVAL;VALUE=DURATION:{refresh_interval}",
    ]
    for event in sorted(events, key=_event_sort_key):
        lines.extend(build_event_lines(event))
    lines.append("END:VCALENDAR")
    return lines
