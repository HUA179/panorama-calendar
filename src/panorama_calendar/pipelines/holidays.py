"""Build holiday events from a transcribed official notice."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from panorama_calendar.models import Alarm, EventKind, EventRecord
from panorama_calendar.models.enums import CalendarKind
from panorama_calendar.models.source import SourceReference
from panorama_calendar.sources.datasets import HolidayDataset, HolidayPeriod

CALENDAR_CATEGORY: dict[CalendarKind, str] = {
    CalendarKind.CN_HOLIDAY: "法定节假日",
    CalendarKind.GX_HOLIDAY: "广西地方假期",
}

#: Suffix marking a rest-period event in its summary.
REST_SUFFIX = "（休）"
#: Suffix marking an adjustment-workday event in its summary.
WORKDAY_SUFFIX = "（班）"
#: Fallback label when the notice does not tie an adjustment to one festival.
GENERIC_WORKDAY_LABEL = "法定假日"
#: Fallback label when the adjustment only exists because of a weekend swap.
WEEKEND_WORKDAY_LABEL = "调休补班"


def _rest_summary(period: HolidayPeriod) -> str:
    """Name a rest span as ``<festival>（休）``."""
    return f"{period.name}{REST_SUFFIX}"


def _workday_label(dataset: HolidayDataset, reason: str) -> str:
    """Name the festival an adjustment workday belongs to, with fallbacks.

    The notice usually states which festival the swap serves. When it does not
    (or the day merely restores a weekend), fall back to a generic label so the
    summary never renders a dangling ``（班）``.
    """
    if any(period.name == reason for period in dataset.periods):
        return reason
    if "周末" in reason:
        return WEEKEND_WORKDAY_LABEL
    return GENERIC_WORKDAY_LABEL


def _workday_summary(dataset: HolidayDataset, reason: str) -> str:
    """Name an adjustment workday as ``<festival>（班）``."""
    return f"{_workday_label(dataset, reason)}{WORKDAY_SUFFIX}"


def _source_reference(dataset: HolidayDataset) -> SourceReference:
    """Wrap the notice provenance into a reusable evidence record."""
    return SourceReference(
        url=dataset.notice.url,
        authority=dataset.notice.publisher,
        retrieved_at=dataset.notice.retrieved_at,
        content_hash=dataset.evidence_hash,
        evidence_id=dataset.notice.doc_number,
    )


def _rest_description(dataset: HolidayDataset, period: HolidayPeriod) -> str:
    """Explain the span, the adjustment days and the legal basis."""
    lines = [
        f"放假 {period.start:%Y-%m-%d} 至 {period.end:%Y-%m-%d}，共 {period.days} 天。",
    ]
    if period.note:
        lines.append(period.note)
    related = sorted(
        (item for item in dataset.workdays if item.reason == period.name),
        key=lambda item: item.date,
    )
    if related:
        listed = "、".join(f"{item.date:%m月%d日}" for item in related)
        lines.append(f"调休上班：{listed}（在日历中单独显示）。")
    lines.append(f"依据：{dataset.notice.title}（{dataset.notice.doc_number}）。")
    lines.append("原文链接见事件 URL。")
    return "\n".join(lines)


def _workday_description(dataset: HolidayDataset, reason: str) -> str:
    """Explain why a weekend becomes a working day."""
    lines = [
        f"{reason}调休，这一天需要上班。",
        f"依据：{dataset.notice.title}（{dataset.notice.doc_number}）。",
        "原文链接见事件 URL。",
    ]
    return "\n".join(lines)


def build_holiday_events(
    dataset: HolidayDataset,
    *,
    now: datetime | None = None,
) -> list[EventRecord]:
    """Turn one year of a holiday dataset into calendar events.

    Rest periods become one all-day event per continuous span. Adjustment
    workdays become independent all-day events carrying a ``-PT4H`` alarm so the
    reminder lands at 20:00 on the previous local evening.

    Args:
        dataset: Validated dataset for a single year.
        now: Timestamp used for ``DTSTAMP``; injected in tests.

    Returns:
        Rest-period events followed by adjustment-workday events.
    """
    stamp = (now or datetime.now(UTC)).astimezone(UTC)
    source = _source_reference(dataset)
    category = CALENDAR_CATEGORY[dataset.calendar_kind]
    prefix = dataset.calendar_kind.value.lower()
    events: list[EventRecord] = []

    for period in dataset.periods:
        events.append(
            EventRecord(
                event_key=f"{prefix}:rest:{dataset.year}:{period.name}",
                calendar_kind=dataset.calendar_kind,
                event_kind=EventKind.REST_PERIOD,
                summary=_rest_summary(period),
                description=_rest_description(dataset, period),
                start_date=period.start,
                end_date_exclusive=period.end + timedelta(days=1),
                sources=[source],
                categories=[category, "放假"],
                dtstamp=stamp,
            )
        )

    for workday in sorted(dataset.workdays, key=lambda item: item.date):
        events.append(
            EventRecord(
                event_key=f"{prefix}:workday:{workday.date.isoformat()}",
                calendar_kind=dataset.calendar_kind,
                event_kind=EventKind.ADJUSTED_WORKDAY,
                summary=_workday_summary(dataset, workday.reason),
                description=_workday_description(dataset, workday.reason),
                start_date=workday.date,
                end_date_exclusive=workday.date + timedelta(days=1),
                sources=[source],
                categories=[category, "调休上班"],
                alarms=[
                    Alarm(
                        description=f"明天调休上班：{workday.reason}调休，别忘了。",
                        purpose="adjusted-workday-evening",
                    )
                ],
                dtstamp=stamp,
            )
        )

    return events
