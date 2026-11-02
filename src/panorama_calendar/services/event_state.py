"""Persist the last published events so revision chains survive between runs.

A feed's ``SEQUENCE`` only means something if the next build can compare against
what was published before. Rebuilding from scratch would renumber every event
back to zero and clients would ignore genuine corrections. The state file is a
plain JSON snapshot of the published events, written atomically next to the
calendar so a handoff package keeps the chain intact.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path

from panorama_calendar.models.event import EventRecord

STATE_VERSION = 1


class EventStateError(RuntimeError):
    """Raised when a revision state file cannot be trusted."""


def load_event_state(path: Path) -> list[EventRecord]:
    """Load previously published events; a missing file means "first build"."""
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EventStateError(f"cannot read event state {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
        raise EventStateError(f"unsupported event state format in {path}")
    items = payload.get("events")
    if not isinstance(items, list):
        raise EventStateError(f"event state {path} has no event list")
    try:
        return [EventRecord.model_validate(item) for item in items]
    except ValueError as error:
        raise EventStateError(f"invalid event state in {path}: {error}") from error


def save_event_state(path: Path, events: Iterable[EventRecord]) -> str:
    """Write the state atomically and return the SHA-256 of the bytes."""
    payload = {
        "version": STATE_VERSION,
        "events": [event.model_dump(mode="json") for event in events],
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return hashlib.sha256(data).hexdigest()
