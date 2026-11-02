"""Publication guardrails: never let a degraded build replace a good calendar."""

from __future__ import annotations

from pathlib import Path

from panorama_calendar.models.enums import CalendarKind

# Floors are deliberately conservative. They exist to stop an empty or truncated
# parse from overwriting a good feed, not to police editorial decisions.
MINIMUM_EVENTS: dict[CalendarKind, int] = {
    CalendarKind.CN_HOLIDAY: 7,
    CalendarKind.GX_HOLIDAY: 1,
    CalendarKind.MEMORIAL: 10,
}

MAX_EVENT_DROP_RATIO = 0.34


class PublishGuardError(RuntimeError):
    """Raised when a candidate calendar looks degraded and must not be published."""


def count_events_in_file(path: Path) -> int | None:
    """Count ``BEGIN:VEVENT`` occurrences in an existing calendar file.

    Args:
        path: Candidate output path.

    Returns:
        The event count, or ``None`` when the file does not exist or is unreadable.
    """
    if not path.is_file():
        return None
    try:
        return path.read_bytes().count(b"BEGIN:VEVENT")
    except OSError:
        return None


def ensure_publishable(
    calendar_kind: CalendarKind,
    event_count: int,
    *,
    existing_path: Path | None = None,
) -> None:
    """Refuse to publish an empty, tiny or sharply shrunken calendar.

    A missing or unparsable source must never turn into an empty calendar; that
    is the single most damaging failure mode for a subscribed feed.

    Args:
        calendar_kind: Which feed is being built.
        event_count: Number of events in the candidate build.
        existing_path: Previously published file, used for the shrink check.

    Raises:
        PublishGuardError: If the candidate is empty, below the floor, or has
            shrunk by more than ``MAX_EVENT_DROP_RATIO``.
    """
    minimum = MINIMUM_EVENTS.get(calendar_kind)
    if event_count <= 0:
        raise PublishGuardError(
            f"{calendar_kind}: candidate has no events; keeping the last trusted version"
        )
    if minimum is not None and event_count < minimum:
        raise PublishGuardError(
            f"{calendar_kind}: candidate has {event_count} events, below the floor of {minimum}"
        )
    if existing_path is None:
        return
    previous = count_events_in_file(existing_path)
    if previous is None or previous == 0:
        return
    if event_count < previous * (1 - MAX_EVENT_DROP_RATIO):
        raise PublishGuardError(
            f"{calendar_kind}: event count dropped from {previous} to {event_count}; "
            "refusing to publish a degraded calendar"
        )
