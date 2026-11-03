"""F1 schedule identity, timezone, cancellation and omission semantics."""

from datetime import UTC, datetime, timedelta

import pytest

from panorama_calendar.models import EventStatus, F1Session, SessionKind, SourceReference
from panorama_calendar.pipelines import F1ScheduleError, build_f1_schedule_events


def _session(
    kind: SessionKind = SessionKind.RACE,
    *,
    start: datetime | None = None,
    status: EventStatus = EventStatus.CONFIRMED,
    name: str = "São Paulo Grand Prix 2026",
) -> F1Session:
    """Return one deterministic official session for pipeline tests."""
    return F1Session(
        season=2026,
        event_id="brazil",
        grand_prix_name=name,
        session_kind=kind,
        start_at_utc=start or datetime(2026, 11, 8, 17, tzinfo=UTC),
        end_at_utc=(start or datetime(2026, 11, 8, 17, tzinfo=UTC)) + timedelta(hours=2),
        circuit_timezone="America/Sao_Paulo",
        location="São Paulo",
        status=status,
        source=SourceReference(
            url="https://www.formula1.com/en/racing/2026/brazil",
            authority="Formula 1",
            retrieved_at=datetime(2026, 11, 2, tzinfo=UTC),
        ),
    )


def test_schedule_uses_utc_and_iana_display_times() -> None:
    """ICS storage stays UTC while description shows Beijing and circuit time."""
    event = build_f1_schedule_events([_session()])[0]
    assert event.start_at_utc == datetime(2026, 11, 8, 17, tzinfo=UTC)
    assert event.source_timezone == "UTC"
    assert "北京时间：2026-11-09 01:00" in event.description
    assert "赛道当地时间：2026-11-08 14:00" in event.description
    assert event.transparent is False
    assert event.alarms == []


def test_summary_pairs_the_chinese_grand_prix_with_the_bilingual_city() -> None:
    """The title follows the agreed 「大奖赛（城市） | Session」 layout."""
    race = build_f1_schedule_events([_session()])[0]
    assert race.summary == "🏎️ 巴西大奖赛（圣保罗, São Paulo） | 正赛"
    sprint_qualifying = build_f1_schedule_events([_session(SessionKind.SPRINT_QUALIFYING)])[0]
    assert sprint_qualifying.summary == "🏎️ 巴西大奖赛（圣保罗, São Paulo） | 冲刺排位赛"


def test_unknown_round_has_no_reviewed_display_name() -> None:
    """A new slug must be added to the reviewed registry, not guessed."""
    session = _session().model_copy(update={"event_id": "saudi-arabia"})
    with pytest.raises(F1ScheduleError, match="no reviewed Chinese display name"):
        build_f1_schedule_events([session])


def test_reschedule_keeps_uid_and_only_advances_changed_session() -> None:
    """Qualifying is untouched when only the race moves to a new time."""
    original = build_f1_schedule_events(
        [_session(SessionKind.QUALIFYING), _session()],
        now=datetime(2026, 11, 1, tzinfo=UTC),
    )
    revised = build_f1_schedule_events(
        [
            _session(SessionKind.QUALIFYING),
            _session(start=datetime(2026, 11, 8, 18, tzinfo=UTC)),
        ],
        previous=original,
        now=datetime(2026, 11, 2, tzinfo=UTC),
    )
    old_by_kind = {event.summary.rsplit(" | ", 1)[-1]: event for event in original}
    new_by_kind = {event.summary.rsplit(" | ", 1)[-1]: event for event in revised}
    assert new_by_kind["正赛"].uid == old_by_kind["正赛"].uid
    assert new_by_kind["正赛"].sequence == old_by_kind["正赛"].sequence + 1
    assert new_by_kind["排位赛"].sequence == old_by_kind["排位赛"].sequence
    assert new_by_kind["排位赛"].dtstamp == old_by_kind["排位赛"].dtstamp


def test_sponsor_or_event_rename_keeps_stable_uid() -> None:
    """A display-name change revises content without changing identity."""
    original = build_f1_schedule_events([_session()])
    revised = build_f1_schedule_events(
        [_session(name="São Paulo Grand Prix 2026 presented by Sponsor")],
        previous=original,
        now=datetime(2026, 11, 2, tzinfo=UTC),
    )
    assert revised[0].uid == original[0].uid
    assert revised[0].event_key == original[0].event_key
    assert revised[0].sequence == original[0].sequence + 1


def test_cancellation_is_a_same_uid_tombstone() -> None:
    """Explicit cancellation changes only that session and retains its identity."""
    original = build_f1_schedule_events([_session()], now=datetime(2026, 11, 1, tzinfo=UTC))
    revised = build_f1_schedule_events(
        [_session(status=EventStatus.CANCELLED)],
        previous=original,
        now=datetime(2026, 11, 2, tzinfo=UTC),
    )
    assert revised[0].status is EventStatus.CANCELLED
    assert revised[0].uid == original[0].uid
    assert revised[0].sequence == original[0].sequence + 1


def test_missing_source_record_does_not_delete_or_cancel_previous() -> None:
    """A source omission alone never creates a deletion or cancellation."""
    original = build_f1_schedule_events([_session()])
    revised = build_f1_schedule_events([], previous=original)
    assert len(revised) == 1
    assert revised[0].status is EventStatus.CONFIRMED
    assert revised[0].uid == original[0].uid
