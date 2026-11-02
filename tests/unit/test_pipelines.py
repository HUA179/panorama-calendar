"""Pipelines: dataset to calendar events."""

from __future__ import annotations

from datetime import UTC, date, datetime

from panorama_calendar.models import EventKind
from panorama_calendar.models.enums import CalendarKind
from panorama_calendar.pipelines import build_holiday_events, build_memorial_events
from panorama_calendar.sources.datasets import load_anniversary_registry, load_holiday_dataset

NOW = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)


def test_national_events_split_rest_and_workdays() -> None:
    """Seven rest spans plus six adjustment workdays make thirteen events."""
    events = build_holiday_events(load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2026), now=NOW)
    rest = [event for event in events if event.event_kind is EventKind.REST_PERIOD]
    workdays = [event for event in events if event.event_kind is EventKind.ADJUSTED_WORKDAY]
    assert len(rest) == 7
    assert len(workdays) == 6


def test_rest_periods_carry_no_alarm() -> None:
    """Only adjustment workdays remind the user; holidays stay silent."""
    events = build_holiday_events(load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2026), now=NOW)
    for event in events:
        if event.event_kind is EventKind.REST_PERIOD:
            assert event.alarms == []


def test_workdays_use_previous_evening_trigger() -> None:
    """Every adjustment workday has exactly one -PT4H start-relative alarm."""
    events = build_holiday_events(load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2026), now=NOW)
    workdays = [event for event in events if event.event_kind is EventKind.ADJUSTED_WORKDAY]
    assert workdays
    for event in workdays:
        assert len(event.alarms) == 1
        alarm = event.alarms[0]
        assert alarm.trigger == "-PT4H"
        assert alarm.related == "START"
        assert alarm.uid != event.uid


def test_events_are_all_day_with_exclusive_end() -> None:
    """Holiday feeds never carry timed fields."""
    events = build_holiday_events(load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2026), now=NOW)
    for event in events:
        assert event.start_date is not None
        assert event.end_date_exclusive is not None
        assert event.start_at_utc is None
        assert event.end_date_exclusive > event.start_date


def test_spring_festival_span_is_nine_days() -> None:
    """The Spring Festival event covers 2026-02-15 .. 2026-02-23 inclusive."""
    events = build_holiday_events(load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2026), now=NOW)
    spring = next(event for event in events if "春节" in (event.summary or ""))
    assert spring.start_date == date(2026, 2, 15)
    assert spring.end_date_exclusive == date(2026, 2, 24)


def test_guangxi_makeup_rest_merges_into_one_span() -> None:
    """Guangxi 2026 has a single four-day span and no workday events."""
    events = build_holiday_events(load_holiday_dataset(CalendarKind.GX_HOLIDAY, 2026), now=NOW)
    assert len(events) == 1
    event = events[0]
    assert event.start_date == date(2026, 4, 17)
    assert event.end_date_exclusive == date(2026, 4, 21)
    assert event.alarms == []
    assert event.calendar_kind is CalendarKind.GX_HOLIDAY


def test_uids_are_stable_across_rebuilds() -> None:
    """A rebuilt calendar must not drift its identifiers."""
    first = build_holiday_events(load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2026), now=NOW)
    second = build_holiday_events(
        load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2026),
        now=datetime(2026, 11, 3, 9, 0, tzinfo=UTC),
    )
    assert [event.uid for event in first] == [event.uid for event in second]
    assert len({event.uid for event in first}) == len(first)


def test_memorial_events_are_quiet() -> None:
    """Memorial days are all-day, alarm-free and marked transparent."""
    events = build_memorial_events(load_anniversary_registry(), 2026, now=NOW)
    assert len(events) >= 18
    for event in events:
        assert event.calendar_kind is CalendarKind.MEMORIAL
        assert event.event_kind is EventKind.MEMORIAL_DAY
        assert event.alarms == []
        assert event.transparent is True
        assert event.start_date is not None


def test_memorial_events_exclude_local_observances() -> None:
    """Only nationally established days appear; local events never do."""
    events = build_memorial_events(load_anniversary_registry(), 2026, now=NOW)
    summaries = {event.summary for event in events}
    assert "武汉沦陷日" not in summaries
    assert "烈士纪念日" in summaries
