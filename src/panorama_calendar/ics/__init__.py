"""Public ICS construction API."""

from collections.abc import Iterable

from panorama_calendar.ics.builder import (
    DEFAULT_REFRESH_INTERVAL,
    build_calendar_lines,
    build_event_lines,
)
from panorama_calendar.ics.serializer import serialize_logical_lines
from panorama_calendar.ics.validator import validate_ics_bytes
from panorama_calendar.models.event import EventRecord


def render_calendar(
    events: Iterable[EventRecord],
    calendar_name: str,
    refresh_interval: str = DEFAULT_REFRESH_INTERVAL,
) -> bytes:
    """Build, serialize and validate a complete calendar."""
    data = serialize_logical_lines(
        build_calendar_lines(events, calendar_name, refresh_interval=refresh_interval)
    )
    validate_ics_bytes(data)
    return data


__all__ = [
    "DEFAULT_REFRESH_INTERVAL",
    "build_calendar_lines",
    "build_event_lines",
    "render_calendar",
    "serialize_logical_lines",
    "validate_ics_bytes",
]
