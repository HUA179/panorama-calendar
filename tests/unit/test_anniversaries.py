"""Memorial-day register behaviour."""

from __future__ import annotations

from datetime import date

from panorama_calendar.sources.datasets import load_anniversary_registry


def test_fixed_date_resolution() -> None:
    """A fixed-date entry lands on the same month and day every year."""
    registry = load_anniversary_registry()
    resolved = dict(
        (entry.key, moment) for entry, moment in registry.resolve_year(2026)
    )
    assert resolved["memorial:martyrs-day"] == date(2026, 9, 30)
    assert resolved["memorial:constitution-day"] == date(2026, 12, 4)


def test_nth_weekday_resolution() -> None:
    """全国助残日 is the third Sunday of May, which is 2026-05-17."""
    registry = load_anniversary_registry()
    resolved = dict(
        (entry.key, moment) for entry, moment in registry.resolve_year(2026)
    )
    assert resolved["memorial:national-disability-day"] == date(2026, 5, 17)
    assert resolved["memorial:national-disability-day"].weekday() == 6


def test_entry_before_establishment_is_skipped() -> None:
    """Entries never appear in years before they were established."""
    registry = load_anniversary_registry()
    keys_2024 = {entry.key for entry, _ in registry.resolve_year(2024)}
    keys_2026 = {entry.key for entry, _ in registry.resolve_year(2026)}
    assert "memorial:taiwan-restoration-day" not in keys_2024
    assert "memorial:taiwan-restoration-day" in keys_2026


def test_resolution_is_sorted_by_date() -> None:
    """A feed must be emitted in chronological order."""
    registry = load_anniversary_registry()
    moments = [moment for _, moment in registry.resolve_year(2026)]
    assert moments == sorted(moments)


def test_year_has_no_duplicate_dates_after_dedup_by_name() -> None:
    """Two different memorial days may share a date but never share an identity."""
    registry = load_anniversary_registry()
    entries = registry.resolve_year(2026)
    keys = [entry.key for entry, _ in entries]
    assert len(keys) == len(set(keys))
