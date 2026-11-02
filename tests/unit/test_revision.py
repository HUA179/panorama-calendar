"""Semantic revision tests."""

from datetime import UTC, datetime

import pytest

from panorama_calendar.models import EventRecord
from panorama_calendar.services.revision import reconcile_events

NOW = datetime(2026, 2, 1, tzinfo=UTC)


def test_unchanged_event_reuses_revision_metadata(workday_event: EventRecord) -> None:
    """A scheduled rebuild must not notify clients about unchanged content."""
    original = workday_event.model_copy(deep=True)
    original.sequence = 4
    result = reconcile_events(
        [original],
        [workday_event],
        now=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert result[0].sequence == 4
    assert result[0].dtstamp == original.dtstamp


def test_changed_event_advances_only_its_sequence(workday_event: EventRecord) -> None:
    """A business change increments SEQUENCE and keeps the same UID."""
    original = workday_event.model_copy(deep=True)
    original.sequence = 4
    changed = workday_event.model_copy(deep=True)
    changed.summary = "调休上班｜已修订"
    result = reconcile_events(
        [original],
        [changed],
        now=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert result[0].uid == original.uid
    assert result[0].sequence == 5
    assert result[0].last_modified == NOW


def test_content_rollback_advances_between_adjacent_builds(workday_event: EventRecord) -> None:
    """Repeating an older value is still a new revision, not a rewind."""
    first = reconcile_events([], [workday_event], now=NOW)[0]
    changed = workday_event.model_copy(deep=True)
    changed.summary = "调休上班｜中间版本"
    second = reconcile_events([first], [changed], now=NOW)[0]
    rolled_back = reconcile_events([second], [workday_event], now=NOW)[0]

    assert rolled_back.summary == workday_event.summary
    assert rolled_back.sequence == 2
    assert rolled_back.uid == first.uid


def test_lost_snapshot_continues_from_the_published_floor(workday_event: EventRecord) -> None:
    """A missing state file must not restart the feed at SEQUENCE 0."""
    published = workday_event.model_copy(deep=True)
    published.sequence = 7

    result = reconcile_events(
        [],
        [workday_event],
        now=NOW,
        minimum_sequences={published.uid: 7},
    )

    assert result[0].sequence == 8
    assert result[0].uid == published.uid


def test_stale_snapshot_catches_up_without_inventing_a_revision(
    workday_event: EventRecord,
) -> None:
    """Identical content on a lagging snapshot reuses the floor, not the floor plus one."""
    stale = workday_event.model_copy(deep=True)
    stale.sequence = 2

    result = reconcile_events(
        [stale],
        [workday_event],
        now=NOW,
        minimum_sequences={stale.uid: 9},
    )

    assert result[0].sequence == 9
    assert result[0].dtstamp == NOW


def test_floor_below_the_snapshot_is_ignored(workday_event: EventRecord) -> None:
    """A floor read from an old feed cannot pull an up-to-date snapshot back."""
    current = workday_event.model_copy(deep=True)
    current.sequence = 5

    result = reconcile_events(
        [current],
        [workday_event],
        now=NOW,
        minimum_sequences={current.uid: 2},
    )

    assert result[0].sequence == 5
    assert result[0].dtstamp == current.dtstamp


def test_negative_floor_is_rejected(workday_event: EventRecord) -> None:
    """A corrupt floor fails loudly instead of publishing a lower version."""
    with pytest.raises(ValueError, match="must not be negative"):
        reconcile_events(
            [],
            [workday_event],
            now=NOW,
            minimum_sequences={workday_event.uid or "": -1},
        )
