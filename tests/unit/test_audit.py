"""Publish audit trail behaviour."""

from __future__ import annotations

import json
from pathlib import Path

from panorama_calendar.services.audit import append_publish_record


def _record(digest: str, events: int = 13) -> dict[str, object]:
    return {
        "action": "build",
        "feed": "cn-holidays",
        "events": events,
        "sequence_min": 0,
        "sequence_max": 0,
        "ics_sha256": digest,
    }


def _lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_every_record_is_appended_by_default(tmp_path: Path) -> None:
    """Default behaviour stays append-only, even for identical digests."""
    trail = tmp_path / "feed.revisions.jsonl"

    assert append_publish_record(trail, _record("aaa")) is True
    assert append_publish_record(trail, _record("aaa")) is True

    assert len(_lines(trail)) == 2


def test_unchanged_digest_is_skipped_when_asked(tmp_path: Path) -> None:
    """A rerun that reproduces the same bytes records nothing new."""
    trail = tmp_path / "feed.revisions.jsonl"

    assert append_publish_record(trail, _record("aaa"), skip_if_unchanged=True) is True
    assert append_publish_record(trail, _record("aaa"), skip_if_unchanged=True) is False

    records = _lines(trail)
    assert len(records) == 1
    assert records[0]["ics_sha256"] == "aaa"


def test_changed_digest_is_always_recorded(tmp_path: Path) -> None:
    """Real revisions must never be swallowed by the dedupe check."""
    trail = tmp_path / "feed.revisions.jsonl"

    append_publish_record(trail, _record("aaa"), skip_if_unchanged=True)
    assert append_publish_record(trail, _record("bbb"), skip_if_unchanged=True) is True

    assert [record["ics_sha256"] for record in _lines(trail)] == ["aaa", "bbb"]


def test_rollback_to_a_previous_digest_is_recorded(tmp_path: Path) -> None:
    """A -> B -> A is a real change twice, despite repeating the first digest."""
    trail = tmp_path / "feed.revisions.jsonl"

    for digest in ("aaa", "bbb", "aaa"):
        append_publish_record(trail, _record(digest), skip_if_unchanged=True)

    assert [record["ics_sha256"] for record in _lines(trail)] == ["aaa", "bbb", "aaa"]


def test_corrupt_trailing_line_does_not_block_publication(tmp_path: Path) -> None:
    """A truncated line must degrade to 'no previous record', not raise."""
    trail = tmp_path / "feed.revisions.jsonl"
    trail.write_text('{"ics_sha256": "aaa"}\n{"broken": \n', encoding="utf-8")

    assert append_publish_record(trail, _record("bbb"), skip_if_unchanged=True) is True
    first = json.loads(trail.read_text(encoding="utf-8").splitlines()[0])
    assert first["ics_sha256"] == "aaa"
    assert "bbb" in trail.read_text(encoding="utf-8")


def test_record_without_digest_is_never_deduped(tmp_path: Path) -> None:
    """Records that carry no digest have nothing to compare, so they are kept."""
    trail = tmp_path / "feed.revisions.jsonl"
    record = {"action": "build", "feed": "cn-holidays", "events": 13}

    append_publish_record(trail, record, skip_if_unchanged=True)
    append_publish_record(trail, record, skip_if_unchanged=True)

    assert len(_lines(trail)) == 2
