"""Rollback must restore content without ever rewinding SEQUENCE."""

from datetime import UTC, date, datetime

import pytest

from panorama_calendar.models import CalendarKind, EventKind, EventRecord
from panorama_calendar.services.rollback import RollbackError, rollback_to_snapshot

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _event(key: str, summary: str, *, sequence: int = 0) -> EventRecord:
    return EventRecord(
        event_key=key,
        calendar_kind=CalendarKind.CN_HOLIDAY,
        event_kind=EventKind.ADJUSTED_WORKDAY,
        summary=summary,
        start_date=date(2026, 12, 15),
        end_date_exclusive=date(2026, 12, 16),
        sequence=sequence,
    )


def test_rollback_restores_content_as_a_new_revision() -> None:
    """The old summary comes back, but the version keeps moving forward."""
    snapshot = [_event("cn:2026:rollback:a", "旧内容", sequence=1)]
    current = [_event("cn:2026:rollback:a", "新内容", sequence=4)]

    result = rollback_to_snapshot(
        snapshot, current, calendar_kind=CalendarKind.CN_HOLIDAY, now=NOW
    )

    assert result[0].summary == "旧内容"
    assert result[0].sequence == 5
    assert result[0].uid == current[0].uid
    assert result[0].last_modified == NOW


def test_rollback_respects_the_published_floor() -> None:
    """A stale local snapshot cannot drag the version below the live feed."""
    snapshot = [_event("cn:2026:rollback:b", "旧内容", sequence=1)]
    current = [_event("cn:2026:rollback:b", "新内容", sequence=4)]

    result = rollback_to_snapshot(
        snapshot,
        current,
        calendar_kind=CalendarKind.CN_HOLIDAY,
        minimum_sequences={current[0].uid or "": 9},
        now=NOW,
    )

    assert result[0].sequence == 10


def test_rollback_keeps_events_that_the_snapshot_never_had() -> None:
    """Rollback is not a delete: newer events survive untouched."""
    snapshot = [_event("cn:2026:rollback:c", "旧内容", sequence=1)]
    current = [
        _event("cn:2026:rollback:c", "新内容", sequence=4),
        _event("cn:2026:rollback:extra", "后加的事件", sequence=3),
    ]

    result = rollback_to_snapshot(
        snapshot, current, calendar_kind=CalendarKind.CN_HOLIDAY, now=NOW
    )
    kept = next(event for event in result if event.event_key.endswith("extra"))

    assert kept.summary == "后加的事件"
    assert kept.sequence == 3


def test_empty_snapshot_is_refused() -> None:
    """An empty snapshot would silently publish an unrelated feed."""
    with pytest.raises(RollbackError, match="no CN_HOLIDAY events"):
        rollback_to_snapshot(
            [],
            [_event("cn:2026:rollback:d", "现在", sequence=2)],
            calendar_kind=CalendarKind.CN_HOLIDAY,
        )


def test_empty_current_state_is_refused() -> None:
    """Without a current state there is no revision chain to advance."""
    with pytest.raises(RollbackError, match="no CN_HOLIDAY events to roll back onto"):
        rollback_to_snapshot(
            [_event("cn:2026:rollback:e", "旧", sequence=1)],
            [],
            calendar_kind=CalendarKind.CN_HOLIDAY,
        )


def test_snapshot_from_another_feed_is_ignored() -> None:
    """A mixed snapshot must not leak events across subscriptions."""
    foreign = EventRecord(
        event_key="f1:2026:mexico:race",
        calendar_kind=CalendarKind.F1_SCHEDULE,
        event_kind=EventKind.F1_SESSION,
        summary="F1｜Mexico｜正赛",
        start_at_utc=datetime(2026, 11, 1, 20, tzinfo=UTC),
    )

    with pytest.raises(RollbackError, match="no CN_HOLIDAY events"):
        rollback_to_snapshot(
            [foreign],
            [_event("cn:2026:rollback:f", "现在", sequence=2)],
            calendar_kind=CalendarKind.CN_HOLIDAY,
        )
