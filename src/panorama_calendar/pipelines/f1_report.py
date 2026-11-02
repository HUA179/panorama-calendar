"""Convert normalised F1 race reports into alarm-free all-day events."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta

from panorama_calendar.models import (
    CalendarKind,
    EventKind,
    EventRecord,
    EventStatus,
    ResultStatus,
)
from panorama_calendar.models.f1 import F1RaceReport
from panorama_calendar.services.revision import reconcile_events

_STATUS_LABELS = {
    ResultStatus.PROVISIONAL: "暂定成绩（以 FIA 最终成绩为准）",
    ResultStatus.FINAL: "FIA 最终成绩",
    ResultStatus.AMENDED: "改判后成绩（FIA 已重新发布最终成绩）",
}
_PODIUM_TITLES = ("冠军", "亚军", "季军")
_STATUS_RANK = {
    ResultStatus.NOT_AVAILABLE: 0,
    ResultStatus.PROVISIONAL: 1,
    ResultStatus.FINAL: 2,
    ResultStatus.AMENDED: 3,
}


class F1ReportError(RuntimeError):
    """Raised when a rebuild would publish less certainty than it already has."""


def _candidate_event(report: F1RaceReport) -> EventRecord:
    """Build one self-contained report event from the normalised facts."""
    summary = f"F1战报｜{report.grand_prix_name}｜正赛"
    if report.status is ResultStatus.PROVISIONAL:
        summary += "（暂定）"

    lines = [f"状态：{_STATUS_LABELS[report.status]}"]
    if report.official_name and report.official_name != report.grand_prix_name:
        lines.append(f"赛事：{report.official_name}")
    for title, entry in zip(_PODIUM_TITLES, report.podium, strict=False):
        lines.append(f"{title}：{entry.driver}（{entry.team}，{entry.points} 分）")
    if report.pole is not None:
        pole = report.pole
        pole_time = f"，{pole.time}" if pole.time else ""
        lines.append(f"杆位：{pole.driver}（{pole.team}{pole_time}）")
    lines.append(f"完赛：{report.classified_count} 人；退赛：{report.dnf_count} 人")
    lines.append(f"来源：F1 官方成绩页 {report.result_source.url}")
    if report.grid_source is not None:
        lines.append(f"发车顺位：{report.grid_source.url}")
    if report.fia_classification_url is not None:
        fia_label = (
            "FIA 最终成绩文件"
            if report.status is not ResultStatus.PROVISIONAL
            else "FIA 暂定成绩文件"
        )
        lines.append(f"{fia_label}：{report.fia_classification_url}")

    sources = [report.result_source]
    if report.grid_source is not None:
        sources.append(report.grid_source)

    return EventRecord(
        event_key=report.event_key,
        calendar_kind=CalendarKind.F1_REPORT,
        event_kind=EventKind.F1_REPORT,
        summary=summary,
        description="\n".join(lines),
        start_date=report.race_date,
        end_date_exclusive=report.race_date + timedelta(days=1),
        status=EventStatus.CONFIRMED,
        result_status=report.status,
        sources=sources,
        categories=["F1", "战报"],
        transparent=True,
    )


def build_f1_report_events(
    reports: Iterable[F1RaceReport],
    *,
    previous: Iterable[EventRecord] = (),
    now: datetime | None = None,
    minimum_sequences: Mapping[str, int] | None = None,
) -> list[EventRecord]:
    """Build and reconcile race reports on their own revision chain.

    Reports never share UIDs or sequence numbers with the schedule feed.
    Rounds absent from a new build keep their previous event unchanged;
    only content changes advance SEQUENCE. A round that already carries a
    final or amended classification is never rewritten as provisional: a
    missing FIA document means "leave it alone", not "downgrade it".
    """
    previous_events = [event for event in previous if event.calendar_kind is CalendarKind.F1_REPORT]
    previous_by_key = {event.event_key: event for event in previous_events}
    candidates = []
    seen_keys: set[str] = set()
    for report in reports:
        candidate = _candidate_event(report)
        if candidate.event_key in seen_keys:
            raise F1ReportError(f"{report.grand_prix_name}: duplicate report in one build")
        seen_keys.add(candidate.event_key)
        old = previous_by_key.get(candidate.event_key)
        if old is not None and _STATUS_RANK[old.result_status] > _STATUS_RANK[
            candidate.result_status
        ]:
            raise F1ReportError(
                f"{report.grand_prix_name}: refusing to downgrade "
                f"{old.result_status} to {candidate.result_status}"
            )
        candidates.append(candidate)
    candidate_keys = {event.event_key for event in candidates}
    retained = [event for event in previous_events if event.event_key not in candidate_keys]
    return reconcile_events(
        previous_events,
        [*candidates, *retained],
        now=now or datetime.now(UTC),
        minimum_sequences=minimum_sequences,
    )
