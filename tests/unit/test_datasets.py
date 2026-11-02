"""Dataset loading, integrity rules and evidence hashing."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from panorama_calendar.models.enums import CalendarKind
from panorama_calendar.sources.datasets import (
    AdjustmentWorkday,
    DatasetError,
    HolidayDataset,
    HolidayPeriod,
    NoticeHeader,
    available_holiday_years,
    load_anniversary_registry,
    load_holiday_dataset,
)

CST = timezone(timedelta(hours=8))


def _header() -> NoticeHeader:
    """Minimal provenance block for synthetic datasets."""
    return NoticeHeader(
        title="测试通知",
        doc_number="测〔2026〕1号",
        publisher="测试机关",
        published_at=date(2025, 11, 1),
        url="https://example.gov.cn/notice",
        retrieved_at=datetime(2026, 11, 2, 15, 0, tzinfo=CST),
    )


def test_loads_2026_national_dataset() -> None:
    """The shipped 2026 notice has seven rest periods and six workdays."""
    dataset = load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2026)
    assert len(dataset.periods) == 7
    assert len(dataset.workdays) == 6
    assert dataset.notice.doc_number == "国办发明电〔2025〕7号"
    assert [period.name for period in dataset.periods][0] == "元旦"


def test_loads_2026_guangxi_dataset() -> None:
    """Guangxi has one four-day span that merges statutory days with makeup rest."""
    dataset = load_holiday_dataset(CalendarKind.GX_HOLIDAY, 2026)
    assert len(dataset.periods) == 1
    period = dataset.periods[0]
    assert period.days == 4
    assert period.start == date(2026, 4, 17)
    assert dataset.workdays == []


def test_rest_dates_expands_every_day() -> None:
    """A nine-day Spring Festival span expands to nine concrete dates."""
    dataset = load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2026)
    spring = next(period for period in dataset.periods if period.name == "春节")
    expected = {spring.start + timedelta(days=offset) for offset in range(9)}
    assert dataset.rest_dates() >= expected
    assert len(expected) == 9
    assert not any(
        workday.date in expected for workday in dataset.workdays
    )


def test_evidence_hash_is_stable_hex() -> None:
    """The evidence hash is deterministic and identifies the transcribed text."""
    dataset = load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2026)
    assert len(dataset.evidence_hash) == 64
    assert dataset.evidence_hash == load_holiday_dataset(
        CalendarKind.CN_HOLIDAY, 2026
    ).evidence_hash
    assert dataset.evidence_hash != load_holiday_dataset(
        CalendarKind.GX_HOLIDAY, 2026
    ).evidence_hash


def test_declared_day_count_must_match_span() -> None:
    """A mismatch between 共N天 and the actual span is rejected at load time."""
    with pytest.raises(ValueError, match="declared 3 days"):
        HolidayPeriod(
            name="测试",
            start=date(2026, 1, 1),
            end=date(2026, 1, 2),
            days=3,
            raw="测试原文",
        )


def test_overlapping_periods_rejected() -> None:
    """Two periods sharing a day would create duplicate calendar entries."""
    with pytest.raises(ValueError, match="overlap"):
        HolidayDataset(
            schema_version=1,
            year=2026,
            calendar_kind=CalendarKind.CN_HOLIDAY,
            notice=_header(),
            periods=[
                HolidayPeriod(
                    name="甲",
                    start=date(2026, 1, 1),
                    end=date(2026, 1, 3),
                    days=3,
                    raw="甲原文",
                ),
                HolidayPeriod(
                    name="乙",
                    start=date(2026, 1, 3),
                    end=date(2026, 1, 4),
                    days=2,
                    raw="乙原文",
                ),
            ],
        )


def test_workday_inside_rest_period_rejected() -> None:
    """A date cannot be both a holiday and an adjustment workday."""
    with pytest.raises(ValueError, match="falls inside"):
        HolidayDataset(
            schema_version=1,
            year=2026,
            calendar_kind=CalendarKind.CN_HOLIDAY,
            notice=_header(),
            periods=[
                HolidayPeriod(
                    name="甲",
                    start=date(2026, 1, 1),
                    end=date(2026, 1, 3),
                    days=3,
                    raw="甲原文",
                )
            ],
            workdays=[
                AdjustmentWorkday(date=date(2026, 1, 2), reason="甲", raw="1月2日上班。")
            ],
        )


def test_missing_year_reports_available_years() -> None:
    """Asking for an untranscribed year fails loudly instead of guessing."""
    with pytest.raises(DatasetError, match="available"):
        load_holiday_dataset(CalendarKind.CN_HOLIDAY, 2031)


def test_unknown_calendar_kind_has_no_datasets() -> None:
    """F1 feeds are not backed by transcribed holiday notices."""
    assert available_holiday_years(CalendarKind.F1_SCHEDULE) == []


def test_anniversary_registry_is_complete() -> None:
    """The shipped register covers every entry with a legal basis."""
    registry = load_anniversary_registry()
    assert len(registry.entries) >= 18
    assert all(entry.legal_basis for entry in registry.entries)


def test_packaged_datasets_are_shipped() -> None:
    """Data files must live inside the installed package, not the repo root."""
    resource = Path(__file__).parents[2] / "src" / "panorama_calendar" / "data"
    assert (resource / "cn_holidays" / "2026.json").is_file()
    assert (resource / "anniversaries.json").is_file()
