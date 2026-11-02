"""Republish an older snapshot as a brand new revision.

Rolling back is not "restore the old file": clients cache by ``UID`` and only
accept a component when ``SEQUENCE`` is higher than what they hold. Restoring the
old numbers would look like nothing happened. This module therefore treats the
old snapshot as *candidate content* and runs it through the normal reconciliation,
so the content returns to the old value while the version keeps moving forward.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from panorama_calendar.models import CalendarKind, EventRecord
from panorama_calendar.services.revision import reconcile_events


class RollbackError(RuntimeError):
    """Raised when a rollback cannot be expressed as a forward revision."""


def rollback_to_snapshot(
    snapshot: Iterable[EventRecord],
    current: Iterable[EventRecord],
    *,
    calendar_kind: CalendarKind,
    minimum_sequences: Mapping[str, int] | None = None,
    now: datetime | None = None,
) -> list[EventRecord]:
    """Restore the snapshot's content while advancing every changed sequence.

    Events that exist now but not in the snapshot are kept unchanged: this
    project never deletes an event silently, and a cancellation must come from an
    explicit official record rather than from a rollback.

    Args:
        snapshot: Events taken from an older revision state file.
        current: Events from the revision state this build would otherwise use.
        calendar_kind: Feed being rolled back; other feeds in the same file are
            ignored so a mixed snapshot cannot leak across subscriptions.
        minimum_sequences: Sequence floor read from the live feed.
        now: Revision timestamp, injectable for deterministic tests.

    Returns:
        Events ready to serialise, with ``SEQUENCE`` strictly ahead of the
        current state wherever the content differs.

    Raises:
        RollbackError: The snapshot holds nothing for this feed, or the current
            state is empty (there would be no revision chain to advance).
    """
    snapshot_events = [event for event in snapshot if event.calendar_kind is calendar_kind]
    current_events = [event for event in current if event.calendar_kind is calendar_kind]
    if not snapshot_events:
        raise RollbackError(f"snapshot contains no {calendar_kind.value} events")
    if not current_events:
        raise RollbackError(
            f"current state contains no {calendar_kind.value} events to roll back onto"
        )

    restored_keys = {event.event_key for event in snapshot_events}
    untouched = [event for event in current_events if event.event_key not in restored_keys]
    return reconcile_events(
        current_events,
        [*snapshot_events, *untouched],
        now=now or datetime.now(UTC),
        minimum_sequences=minimum_sequences,
    )
