"""Append-only record of what each build published.

The state file only keeps the latest snapshot, and a rollback rewrites it. This
trail is the cheap answer to "why did this feed change on that day" without
keeping every historic calendar around: one JSON line per publication.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path


def append_publish_record(
    path: Path,
    record: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> None:
    """Append one publication record as a JSON line.

    Args:
        path: Destination ``.jsonl`` file. Created on first write.
        record: Action, feed, event count, sequence range and feed digest.
        now: Timestamp override, injectable for deterministic tests.
    """
    stamp = (now or datetime.now(UTC)).astimezone(UTC)
    payload = {"published_at": stamp.isoformat(), **record}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
