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


def _last_record(path: Path) -> dict[str, object] | None:
    """Return the newest record, or ``None`` when the trail is empty.

    Only the final line is read: the file grows by one line per publication and
    is never rewritten, so a full parse would be wasted work. A corrupt trailing
    line is ignored rather than fatal — the audit trail must never block a
    publication.
    """
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def append_publish_record(
    path: Path,
    record: Mapping[str, object],
    *,
    now: datetime | None = None,
    skip_if_unchanged: bool = False,
) -> bool:
    """Append one publication record as a JSON line.

    Args:
        path: Destination ``.jsonl`` file. Created on first write.
        record: Action, feed, event count, sequence range and feed digest.
        now: Timestamp override, injectable for deterministic tests.
        skip_if_unchanged: When true, a record whose ``ics_sha256`` matches the
            previous line is dropped. Unchanged builds then leave the whole
            state branch untouched instead of adding a no-op commit every run.

    Returns:
        ``True`` if a line was written, ``False`` if it was skipped.
    """
    if skip_if_unchanged and "ics_sha256" in record:
        previous = _last_record(path)
        if previous is not None and previous.get("ics_sha256") == record["ics_sha256"]:
            return False
    stamp = (now or datetime.now(UTC)).astimezone(UTC)
    payload = {"published_at": stamp.isoformat(), **record}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return True
