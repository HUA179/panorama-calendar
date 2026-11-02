"""Shared test fixtures."""

from datetime import UTC, date, datetime

import pytest

from panorama_calendar.models import Alarm, CalendarKind, EventKind, EventRecord


@pytest.fixture
def workday_event() -> EventRecord:
    """Return an adjusted workday with the required iOS alarm extensions."""
    return EventRecord(
        event_key="cn:2026:adjustment:test-workday",
        calendar_kind=CalendarKind.CN_HOLIDAY,
        event_kind=EventKind.ADJUSTED_WORKDAY,
        summary="调休上班｜测试",
        description="长中文描述，" * 30,
        start_date=date(2026, 12, 15),
        end_date_exclusive=date(2026, 12, 16),
        alarms=[Alarm(description="明天调休上班", purpose="evening-reminder")],
        dtstamp=datetime(2026, 1, 1, tzinfo=UTC),
    )
