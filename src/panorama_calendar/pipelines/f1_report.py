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
from panorama_calendar.models.f1 import F1GridEntry, F1RaceReport, F1ResultEntry
from panorama_calendar.models.source import SourceReference
from panorama_calendar.services.revision import reconcile_events
from panorama_calendar.sources.f1_metadata import (
    F1EventDisplay,
    load_f1_driver_registry,
    load_f1_event_names,
)

_STATUS_LABELS = {
    ResultStatus.PROVISIONAL: "暂定成绩（以 FIA 最终成绩为准）",
    ResultStatus.FINAL: "FIA 最终成绩",
    ResultStatus.AMENDED: "改判后成绩（FIA 已重新发布最终成绩）",
}
_PODIUM_MEDALS = ("🏅", "🥈", "🥉")
_STATUS_RANK = {
    ResultStatus.NOT_AVAILABLE: 0,
    ResultStatus.PROVISIONAL: 1,
    ResultStatus.FINAL: 2,
    ResultStatus.AMENDED: 3,
}


class F1ReportError(RuntimeError):
    """Raised when a rebuild would publish less certainty than it already has."""


def _driver_label(car_number: str, code: str, driver: str, team: str, time: str = "") -> str:
    """Render one driver as ``63 RUS 拉塞尔 🇬🇧 George Russell (Mercedes)``.

    The Chinese name and flag come from the reviewed registry keyed by the
    three-letter code; an unmapped code degrades to number, code and English
    name instead of inventing a translation.
    """
    info = load_f1_driver_registry().get(code) if code else None
    parts = [car_number]
    if code:
        parts.append(code)
    if info is not None:
        parts.append(info.zh)
        parts.append(info.flag)
    parts.append(driver)
    suffix = f"{team}, {time}" if time else team
    return f"{' '.join(parts)} ({suffix})"


def _podium_lines(podium: list[F1ResultEntry]) -> list[str]:
    """Render the top three finishers with medals."""
    return [
        f"{medal} P{entry.position} "
        + _driver_label(entry.car_number, entry.code, entry.driver, entry.team)
        for medal, entry in zip(_PODIUM_MEDALS, podium, strict=False)
    ]


def _pole_line(pole: F1GridEntry) -> str:
    """Render the pole-sitter with the deciding lap time."""
    return "杆位：" + _driver_label(pole.car_number, pole.code, pole.driver, pole.team, pole.time)


def _session_block(title: str, pole: F1GridEntry | None, podium: list[F1ResultEntry]) -> list[str]:
    """Render one 【冲刺赛】or【正赛】block: pole line plus podium."""
    lines = [title]
    if pole is not None:
        lines.append(_pole_line(pole))
    lines.append("成绩：")
    lines.extend(_podium_lines(podium))
    return lines


def _event_display(event_id: str) -> F1EventDisplay:
    """Resolve the reviewed Chinese name and bilingual city for one round."""
    display = load_f1_event_names().get(event_id)
    if display is None:
        raise F1ReportError(f"no reviewed Chinese display name for F1 event: {event_id}")
    return display


def _candidate_event(report: F1RaceReport) -> EventRecord:
    """Build one self-contained report event from the normalised facts."""
    display = _event_display(report.event_id)
    summary = f"🏁 {display.gp_zh}（{display.city_zh}, {display.city_en}） | 战报"
    if report.status is ResultStatus.PROVISIONAL:
        summary += "（暂定）"

    lines = [f"状态：{_STATUS_LABELS[report.status]}"]
    lines.append(f"赛事：{report.official_name or report.grand_prix_name}")
    if report.sprint_results:
        lines.extend(_session_block("【冲刺赛】", report.sprint_pole, report.sprint_podium))
    lines.extend(_session_block("【正赛】", report.pole, report.podium))
    lines.append(f"完赛：{report.classified_count} 人；退赛：{report.dnf_count} 人")
    lines.append(f"来源：{report.result_source.url}")

    sources: list[SourceReference] = []
    for source in (
        report.result_source,
        report.pole_source,
        report.sprint_source,
        report.sprint_pole_source,
    ):
        if source is not None and all(existing.url != source.url for existing in sources):
            sources.append(source)

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
        if (
            old is not None
            and _STATUS_RANK[old.result_status] > _STATUS_RANK[candidate.result_status]
        ):
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
