"""Publication guardrails protect the last trusted feed."""

from __future__ import annotations

from pathlib import Path

import pytest

from panorama_calendar.models.enums import CalendarKind
from panorama_calendar.services.guardrails import (
    PublishGuardError,
    count_events_in_file,
    ensure_publishable,
)


def test_empty_candidate_is_refused() -> None:
    """An empty parse must never overwrite a good calendar."""
    with pytest.raises(PublishGuardError, match="no events"):
        ensure_publishable(CalendarKind.CN_HOLIDAY, 0)


def test_below_floor_is_refused() -> None:
    """A suspiciously small national feed is blocked."""
    with pytest.raises(PublishGuardError, match="below the floor"):
        ensure_publishable(CalendarKind.CN_HOLIDAY, 3)


def test_sharp_drop_is_refused(tmp_path: Path) -> None:
    """Losing a third of the events means something broke upstream."""
    existing = tmp_path / "cn.ics"
    existing.write_bytes(b"BEGIN:VEVENT\r\nEND:VEVENT\r\n" * 30)
    with pytest.raises(PublishGuardError, match="dropped"):
        ensure_publishable(CalendarKind.CN_HOLIDAY, 12, existing_path=existing)


def test_small_shrink_is_allowed(tmp_path: Path) -> None:
    """Losing one or two events is editorial, not a failure."""
    existing = tmp_path / "cn.ics"
    existing.write_bytes(b"BEGIN:VEVENT\r\nEND:VEVENT\r\n" * 14)
    ensure_publishable(CalendarKind.CN_HOLIDAY, 13, existing_path=existing)


def test_missing_previous_file_skips_comparison(tmp_path: Path) -> None:
    """The first ever build has nothing to compare against."""
    ensure_publishable(CalendarKind.CN_HOLIDAY, 13, existing_path=tmp_path / "absent.ics")


def test_count_events_handles_missing_and_broken_files(tmp_path: Path) -> None:
    """Counting returns None instead of raising on absent files."""
    assert count_events_in_file(tmp_path / "absent.ics") is None
    probe = tmp_path / "one.ics"
    probe.write_bytes(b"BEGIN:VEVENT\r\nEND:VEVENT\r\n")
    assert count_events_in_file(probe) == 1
