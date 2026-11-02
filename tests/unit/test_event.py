"""Unified event model tests."""

from datetime import UTC, date, datetime

import pytest

from panorama_calendar.models import CalendarKind, EventKind, EventRecord


def test_timed_event_normalizes_to_utc() -> None:
    """Timed events retain an absolute instant in UTC."""
    event = EventRecord(
        event_key="f1:2026:event:race",
        calendar_kind=CalendarKind.F1_SCHEDULE,
        event_kind=EventKind.F1_SESSION,
        summary="正赛",
        start_at_utc=datetime(2026, 3, 8, 12, 0, tzinfo=UTC),
        end_at_utc=datetime(2026, 3, 8, 14, 0, tzinfo=UTC),
        source_timezone="Asia/Shanghai",
    )
    assert event.start_at_utc is not None
    assert event.start_at_utc.tzinfo == UTC


def test_naive_datetime_is_rejected() -> None:
    """Naive datetimes cannot enter the ICS layer."""
    with pytest.raises(ValueError, match="timezone-aware"):
        EventRecord(
            event_key="f1:invalid",
            calendar_kind=CalendarKind.F1_SCHEDULE,
            event_kind=EventKind.F1_SESSION,
            summary="无效事件",
            start_at_utc=datetime(2026, 3, 8, 12, 0),
        )


def test_all_day_end_must_be_exclusive_and_after_start() -> None:
    """An empty all-day interval is invalid."""
    with pytest.raises(ValueError, match="end_date_exclusive"):
        EventRecord(
            event_key="holiday:invalid",
            calendar_kind=CalendarKind.CN_HOLIDAY,
            event_kind=EventKind.REST_PERIOD,
            summary="无效假期",
            start_date=date(2026, 1, 1),
            end_date_exclusive=date(2026, 1, 1),
        )
