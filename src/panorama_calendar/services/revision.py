"""Semantic diff and event revision handling.

``SEQUENCE`` is only meaningful if it never moves backwards. Comparing against
the previous build alone is not enough: when the stored snapshot is missing or
older than what clients already received, a naive rebuild restarts at zero and
every subscriber silently ignores the publication. The caller therefore passes a
*floor* — the highest sequence already seen on the published feed — and this
module guarantees the new value is the larger of the two, plus one when the
content actually changed.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from panorama_calendar.models.event import EventRecord

_REVISION_METADATA = {"uid", "sequence", "dtstamp", "last_modified", "sources"}


def semantic_fingerprint(event: EventRecord) -> str:
    """Hash business content while excluding revision and fetch metadata."""
    payload = event.model_dump(mode="json", exclude=_REVISION_METADATA)
    payload["alarms"] = [
        alarm.model_dump(mode="json", exclude={"uid", "x_wr_alarmuid"})
        for alarm in event.alarms
    ]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reconcile_events(
    previous: Iterable[EventRecord],
    candidate: Iterable[EventRecord],
    *,
    now: datetime | None = None,
    minimum_sequences: Mapping[str, int] | None = None,
) -> list[EventRecord]:
    """Reuse unchanged metadata and keep every published sequence monotonic.

    Args:
        previous: Events from the last build this process knows about.
        candidate: Freshly built events for the same feed.
        now: Revision timestamp, injectable for deterministic tests.
        minimum_sequences: ``UID`` to highest ``SEQUENCE`` already published on
            the live feed. Guards against a lost or rolled-back snapshot: the
            new value is never below this floor, and a rollback of the content
            still advances the version.

    Returns:
        The reconciled events, in candidate order.

    Raises:
        ValueError: If a floor carries a negative sequence.
    """
    revision_time = (now or datetime.now(UTC)).astimezone(UTC)
    floor = dict(minimum_sequences or {})
    for uid, sequence in floor.items():
        if sequence < 0:
            raise ValueError(f"sequence floor for {uid} must not be negative")

    previous_by_key = {event.event_key: event for event in previous}
    reconciled: list[EventRecord] = []

    for incoming in candidate:
        event = incoming.model_copy(deep=True)
        old = previous_by_key.get(event.event_key)
        if old is not None:
            event.uid = old.uid

        published = max(
            old.sequence if old is not None else -1,
            floor.get(event.uid or "", -1),
        )
        unchanged = old is not None and semantic_fingerprint(old) == semantic_fingerprint(event)

        if unchanged and old is not None and old.sequence == published:
            event.sequence = old.sequence
            event.dtstamp = old.dtstamp
            event.last_modified = old.last_modified
            # Provenance timestamps are fetch metadata, not content. Keeping the
            # freshly stamped ones would rewrite the snapshot on every run and
            # turn a quiet feed into a commit per schedule tick.
            event.sources = old.sources
        elif unchanged:
            # The snapshot lags behind the live feed but the content agrees with
            # it. Catch the number up without inventing a revision clients would
            # have to re-download.
            event.sequence = published
            event.dtstamp = revision_time
            event.last_modified = revision_time
        else:
            event.sequence = published + 1 if published >= 0 else 0
            event.dtstamp = revision_time
            event.last_modified = revision_time if published >= 0 else None
        reconciled.append(event)
    return reconciled
