"""Build memorial-day events from the national register."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from panorama_calendar.models import EventRecord
from panorama_calendar.models.enums import CalendarKind, EventKind
from panorama_calendar.sources.datasets import AnniversaryRegistry


def build_memorial_events(
    registry: AnniversaryRegistry,
    year: int,
    *,
    now: datetime | None = None,
) -> list[EventRecord]:
    """Materialize every register entry that applies to ``year``.

    Memorial days are all-day, non-working-day events: no alarm, transparent
    availability, and the legal basis carried in the description.

    Args:
        registry: Loaded national register.
        year: Calendar year to materialize.
        now: Timestamp used for ``DTSTAMP``; injected in tests.

    Returns:
        One event per applicable entry, sorted by date then key.
    """
    stamp = (now or datetime.now(UTC)).astimezone(UTC)
    events: list[EventRecord] = []

    for entry, moment in registry.resolve_year(year):
        short_key = entry.key.split(":", maxsplit=1)[-1]
        events.append(
            EventRecord(
                event_key=f"memorial:{short_key}:{year}",
                calendar_kind=CalendarKind.MEMORIAL,
                event_kind=EventKind.MEMORIAL_DAY,
                summary=entry.name,
                description=(
                    f"{entry.category}，非放假日。\n"
                    f"依据：{entry.legal_basis}\n"
                    "说明：纪念日不安排放假，也不设置提醒。"
                ),
                start_date=moment,
                end_date_exclusive=moment + timedelta(days=1),
                categories=["纪念日", entry.category],
                dtstamp=stamp,
            )
        )

    return events
