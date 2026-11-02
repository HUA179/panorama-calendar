"""IANA conversion edge cases for F1 source times."""

from datetime import UTC, datetime

import pytest

from panorama_calendar.services.time_rules import local_datetime_to_utc_strict


def test_local_time_uses_iana_dst_rules() -> None:
    """New York summer time is UTC-4 through the timezone database."""
    result = local_datetime_to_utc_strict(datetime(2026, 7, 5, 14, 30), "America/New_York")
    assert result == datetime(2026, 7, 5, 18, 30, tzinfo=UTC)


def test_nonexistent_dst_time_is_rejected() -> None:
    """A spring-forward gap is never silently normalized to another instant."""
    with pytest.raises(ValueError, match="invalid or ambiguous"):
        local_datetime_to_utc_strict(datetime(2026, 3, 8, 2, 30), "America/New_York")


def test_ambiguous_dst_time_is_rejected() -> None:
    """Both folds exist in a fall-back overlap, so automatic choice is unsafe."""
    with pytest.raises(ValueError, match="invalid or ambiguous"):
        local_datetime_to_utc_strict(datetime(2026, 11, 1, 1, 30), "America/New_York")
