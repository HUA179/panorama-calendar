"""End-to-end demo generation for iPhone verification."""

from datetime import date, timedelta
from pathlib import Path

from typer.testing import CliRunner

from panorama_calendar.cli import app
from panorama_calendar.ics import validate_ics_bytes


def test_demo_cli_generates_importable_ics(tmp_path: Path) -> None:
    """The documented command writes valid bytes with the iOS extension."""
    output = tmp_path / "valarm-ios-test.ics"
    result = CliRunner().invoke(
        app,
        ["demo", "--workday", "2026-12-15", "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    data = output.read_bytes()
    validate_ics_bytes(data)
    assert b"BEGIN:VALARM" in data
    assert b"X-WR-ALARMUID:alarm-" in data
    assert b"TRIGGER;RELATED=START:-PT4H" in data


def test_demo_cli_in_days_gives_several_near_chances(tmp_path: Path) -> None:
    """--in-days is repeatable so a missed evening still leaves another alarm."""
    output = tmp_path / "valarm-ios-test.ics"
    result = CliRunner().invoke(
        app,
        ["demo", "--in-days", "1", "--in-days", "2", "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    data = output.read_bytes()
    validate_ics_bytes(data)
    assert data.count(b"BEGIN:VEVENT") == 2
    today = date.today()
    for offset in (1, 2):
        expected = (today + timedelta(days=offset)).strftime("%Y%m%d")
        assert f"DTSTART;VALUE=DATE:{expected}".encode() in data


def test_demo_cli_rejects_ambiguous_or_past_dates(tmp_path: Path) -> None:
    """A caller must not mix both date selectors, and a past alarm is useless."""
    output = str(tmp_path / "x.ics")
    mixed = CliRunner().invoke(
        app,
        ["demo", "--workday", "2026-12-15", "--in-days", "1", "--output", output],
    )
    assert mixed.exit_code != 0
    past = CliRunner().invoke(app, ["demo", "--in-days", "0", "--output", output])
    assert past.exit_code != 0
