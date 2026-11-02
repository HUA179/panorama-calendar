"""Convert authoritative F1 sessions into independently revised timed events."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from panorama_calendar.models import (
    CalendarKind,
    EventKind,
    EventRecord,
    EventStatus,
    SessionKind,
)
from panorama_calendar.models.f1 import F1Session
from panorama_calendar.services.revision import reconcile_events

_SESSION_LABELS = {
    SessionKind.QUALIFYING: "排位赛",
    SessionKind.SPRINT_QUALIFYING: "冲刺排位赛",
    SessionKind.SPRINT: "冲刺赛",
    SessionKind.RACE: "正赛",
}


def _candidate_event(session: F1Session) -> EventRecord:
    """Build one UTC event with both Beijing and circuit-local display times."""
    beijing = session.start_at_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    circuit = session.start_at_utc.astimezone(ZoneInfo(session.circuit_timezone))
    label = _SESSION_LABELS[session.session_kind]
    description = (
        f"赛事：{session.grand_prix_name}\n"
        f"北京时间：{beijing:%Y-%m-%d %H:%M}\n"
        f"赛道当地时间：{circuit:%Y-%m-%d %H:%M}（{session.circuit_timezone}）\n"
        f"来源：Formula 1 官方分站赛历"
    )
    if session.status is EventStatus.CANCELLED:
        description += "\n官方状态：本场 Session 已取消。"
    elif session.status is EventStatus.TENTATIVE:
        description += "\n官方状态：时间暂缓，等待后续确认。"
    return EventRecord(
        event_key=session.event_key,
        calendar_kind=CalendarKind.F1_SCHEDULE,
        event_kind=EventKind.F1_SESSION,
        summary=f"F1｜{session.location or session.grand_prix_name}｜{label}",
        description=description,
        location=session.location,
        start_at_utc=session.start_at_utc,
        end_at_utc=session.end_at_utc,
        source_timezone="UTC",
        status=session.status,
        sources=[session.source],
        categories=["F1", label],
        transparent=False,
    )


def build_f1_schedule_events(
    sessions: Iterable[F1Session],
    *,
    previous: Iterable[EventRecord] = (),
    now: datetime | None = None,
    minimum_sequences: Mapping[str, int] | None = None,
) -> list[EventRecord]:
    """Build and reconcile F1 sessions without deleting unexplained omissions.

    Only four session kinds enter the model. Existing events absent from the new
    official candidate are retained unchanged; cancellation requires an explicit
    official CANCELLED record. Changed sessions alone advance SEQUENCE.
    """
    previous_events = [
        event for event in previous if event.calendar_kind is CalendarKind.F1_SCHEDULE
    ]
    candidates = [_candidate_event(session) for session in sessions]
    candidate_keys = {event.event_key for event in candidates}
    retained = [event for event in previous_events if event.event_key not in candidate_keys]
    return reconcile_events(
        previous_events,
        [*candidates, *retained],
        now=now or datetime.now(UTC),
        minimum_sequences=minimum_sequences,
    )
