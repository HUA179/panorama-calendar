"""End-to-end build of the three milestone-B feeds."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from panorama_calendar.cli import app
from panorama_calendar.ics import validate_ics_bytes

EXPECTED = {
    "cn-holidays-2026.ics": (13, True),
    "guangxi-holidays-2026.ics": (1, False),
    "memorial-days-2026.ics": (18, False),
}


@pytest.fixture
def built(tmp_path: Path) -> Path:
    """Run the documented build command once and return the output directory."""
    result = CliRunner().invoke(app, ["build", "--year", "2026", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    return tmp_path


def test_build_writes_three_valid_feeds(built: Path) -> None:
    """Every feed parses, is byte-valid and has the expected event count."""
    for name, (expected_count, expects_alarm) in EXPECTED.items():
        path = built / name
        assert path.is_file(), f"missing {name}"
        data = path.read_bytes()
        validate_ics_bytes(data)
        assert data.count(b"BEGIN:VEVENT") == expected_count
        assert (b"BEGIN:VALARM" in data) is expects_alarm


def test_national_feed_uses_alarm_and_url_properties(built: Path) -> None:
    """Workdays carry the iOS alarm extension; sources ride on URL, not text."""
    data = (built / "cn-holidays-2026.ics").read_bytes()
    assert data.count(b"TRIGGER;RELATED=START:-PT4H") == 6
    assert data.count(b"X-WR-ALARMUID:alarm-") == 6
    assert b"URL:https://www.gov.cn/zhengce/content/202511/content_7047090.htm" in data


def test_memorial_feed_has_no_alarm_or_url(built: Path) -> None:
    """Memorial days are informational: no reminder, no external link."""
    data = (built / "memorial-days-2026.ics").read_bytes()
    assert b"BEGIN:VALARM" not in data
    assert b"URL:" not in data


def test_guangxi_feed_documents_makeup_rest(built: Path) -> None:
    """The four-day span explains that two days are makeup rest, not work."""
    data = (built / "guangxi-holidays-2026.ics").read_bytes()
    assert b"20260417" in data
    assert b"20260421" in data
    assert b"\xe8\xa1\xa5\xe4\xbc\x91" in data  # 补休


def test_unknown_calendar_is_rejected(tmp_path: Path) -> None:
    """A typo in the feed name fails fast instead of silently building nothing."""
    result = CliRunner().invoke(
        app, ["build", "--calendar", "f1", "--year", "2026", "--out", str(tmp_path)]
    )
    assert result.exit_code != 0


def test_missing_year_reports_failure_without_writing(tmp_path: Path) -> None:
    """A year without a transcribed dataset must not produce an empty file."""
    result = CliRunner().invoke(
        app, ["build", "--calendar", "cn", "--year", "2031", "--out", str(tmp_path)]
    )
    assert result.exit_code != 0
    assert not (tmp_path / "cn-holidays-2031.ics").exists()
