"""End-to-end build of the three milestone-B feeds."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from panorama_calendar.cli import app
from panorama_calendar.ics import validate_ics_bytes
from panorama_calendar.models import CalendarKind, EventRecord

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


def test_rebuild_is_byte_stable(tmp_path: Path) -> None:
    """Static feeds must not churn: a second identical build changes nothing.

    Without a revision chain every run stamped a fresh DTSTAMP, so the file
    changed on every scheduled run even though no holiday had moved.
    """
    runner = CliRunner()
    args = ["build", "--year", "2026", "--out", str(tmp_path)]
    assert runner.invoke(app, args).exit_code == 0
    first = {name: (tmp_path / name).read_bytes() for name in EXPECTED}
    assert runner.invoke(app, args).exit_code == 0
    for name, data in first.items():
        assert (tmp_path / name).read_bytes() == data, f"{name} churned on rebuild"


def test_build_persists_state_and_audit(tmp_path: Path) -> None:
    """Each feed keeps its own snapshot, so revisions survive stateless runs."""
    assert CliRunner().invoke(
        app, ["build", "--year", "2026", "--out", str(tmp_path)]
    ).exit_code == 0
    for stem in ("cn-holidays", "guangxi-holidays", "memorial-days"):
        assert (tmp_path / f"{stem}-2026.state.json").is_file()
        assert (tmp_path / f"{stem}-2026.revisions.jsonl").is_file()


def test_published_sequence_floor_is_respected(tmp_path: Path) -> None:
    """With the snapshot gone, the feed is republished above the live floor.

    Losing the state file means we cannot tell whether the content changed, so
    the only safe move is to publish strictly above what clients already hold.
    """
    runner = CliRunner()
    args = ["build", "--calendar", "cn", "--year", "2026", "--out", str(tmp_path)]
    assert runner.invoke(app, args).exit_code == 0
    ics = tmp_path / "cn-holidays-2026.ics"
    ics.write_bytes(ics.read_bytes().replace(b"SEQUENCE:0", b"SEQUENCE:7"))
    (tmp_path / "cn-holidays-2026.state.json").unlink()

    assert runner.invoke(app, args).exit_code == 0
    data = ics.read_text(encoding="utf-8")
    assert "SEQUENCE:8" in data
    assert "SEQUENCE:7" not in data
    assert "SEQUENCE:0" not in data


def test_changed_content_advances_sequence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real amendment to a holiday must reach clients as a new revision."""
    from panorama_calendar import cli

    runner = CliRunner()
    args = ["build", "--calendar", "gx", "--year", "2026", "--out", str(tmp_path)]
    assert runner.invoke(app, args).exit_code == 0

    original = cli._events_for

    def amended(kind: CalendarKind, year: int) -> list[EventRecord]:
        events = original(kind, year)
        events[0] = events[0].model_copy(update={"summary": events[0].summary + " 调整"})
        return events

    monkeypatch.setattr(cli, "_events_for", amended)
    assert runner.invoke(app, args).exit_code == 0
    data = (tmp_path / "guangxi-holidays-2026.ics").read_text(encoding="utf-8")
    assert "SEQUENCE:1" in data
