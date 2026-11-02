"""Build, validate and atomically write calendar artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from panorama_calendar.ics import render_calendar, validate_ics_bytes
from panorama_calendar.models import EventRecord
from panorama_calendar.models.enums import CalendarKind
from panorama_calendar.services.guardrails import ensure_publishable


@dataclass(frozen=True, slots=True)
class CalendarArtifact:
    """Result of writing one calendar feed to disk."""

    calendar_kind: CalendarKind
    path: Path
    event_count: int
    byte_count: int


def write_calendar(
    events: Iterable[EventRecord],
    calendar_name: str,
    path: Path,
    *,
    calendar_kind: CalendarKind,
) -> CalendarArtifact:
    """Serialize events, validate the bytes, then replace the target atomically.

    The guardrail runs before serialization so a degraded build never reaches
    disk, and the write goes through a temporary file so a crash cannot leave a
    half-written feed behind.

    Args:
        events: Events for this feed.
        calendar_name: Human readable name shown by calendar clients.
        path: Destination ``.ics`` path.
        calendar_kind: Feed identity, used for guardrail floors.

    Returns:
        The written artifact metadata.

    Raises:
        PublishGuardError: If the candidate looks empty or degraded.
        ICSValidationError: If the produced bytes violate RFC 5545 invariants.
    """
    ordered = list(events)
    ensure_publishable(calendar_kind, len(ordered), existing_path=path)
    data = render_calendar(ordered, calendar_name)
    validate_ics_bytes(data)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)

    return CalendarArtifact(
        calendar_kind=calendar_kind,
        path=path,
        event_count=len(ordered),
        byte_count=len(data),
    )
