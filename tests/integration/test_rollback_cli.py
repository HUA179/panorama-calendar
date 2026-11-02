"""End-to-end rollback: restore an older snapshot without rewinding SEQUENCE."""

import shutil
from pathlib import Path

from typer.testing import CliRunner

from panorama_calendar.cli import app
from panorama_calendar.models import F1ResultEntry
from panorama_calendar.sources.f1_results import F1ResultsClient
from tests.integration.test_f1_report_cli import (
    RESULT_URL,
    _source,
    _wire_offline_sources,
)

CORRECTED_RESULTS = [
    F1ResultEntry(
        position="1",
        car_number="16",
        driver="Charles Leclerc",
        team="Ferrari",
        laps=71,
        time_or_status="1:37:00.000",
        points=25,
    )
]


def _build(runner: CliRunner, out: Path) -> None:
    result = runner.invoke(app, ["f1-report", "--year", "2026", "--out", str(out)])
    assert result.exit_code == 0, result.output


def _prepare_two_revisions(
    tmp_path: Path,
    monkeypatch: object,
) -> tuple[CliRunner, Path]:
    """Build once, keep that snapshot, then publish a corrected classification."""
    _wire_offline_sources(monkeypatch)
    runner = CliRunner()
    _build(runner, tmp_path)
    snapshot = tmp_path / "revision-1.state.json"
    shutil.copy(tmp_path / "f1-reports-2026.state.json", snapshot)

    monkeypatch.setattr(  # type: ignore[attr-defined]
        F1ResultsClient,
        "fetch_race_result",
        lambda self, round_link: (CORRECTED_RESULTS, _source(RESULT_URL)),
    )
    _build(runner, tmp_path)
    return runner, snapshot


def test_rollback_republishes_old_content_with_a_higher_sequence(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """The feed returns to the old facts and clients still see a new revision."""
    runner, snapshot = _prepare_two_revisions(tmp_path, monkeypatch)
    changed = (tmp_path / "f1-reports-2026.ics").read_bytes()
    assert b"SEQUENCE:1" in changed
    assert b"Charles Leclerc" in changed

    result = runner.invoke(
        app,
        [
            "rollback",
            "--feed",
            "f1-reports",
            "--year",
            "2026",
            "--from-state",
            str(snapshot),
            "--out",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    data = (tmp_path / "f1-reports-2026.ics").read_bytes()
    assert b"SEQUENCE:2" in data
    assert b"Max Verstappen" in data
    assert b"Charles Leclerc" not in data
    state = (tmp_path / "f1-reports-2026.state.json").read_text(encoding="utf-8")
    assert '"sequence": 2' in state


def test_rollback_dry_run_reports_without_touching_the_feed(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """A rehearsal prints the planned numbers and leaves the files byte-identical."""
    runner, snapshot = _prepare_two_revisions(tmp_path, monkeypatch)
    before = (tmp_path / "f1-reports-2026.ics").read_bytes()

    result = runner.invoke(
        app,
        [
            "rollback",
            "--feed",
            "f1-reports",
            "--year",
            "2026",
            "--from-state",
            str(snapshot),
            "--out",
            str(tmp_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[DRY]" in result.output
    assert "SEQUENCE 1 -> 2" in result.output
    assert (tmp_path / "f1-reports-2026.ics").read_bytes() == before


def test_rollback_rejects_an_unknown_feed(tmp_path: Path) -> None:
    """Typos cannot roll back the wrong subscription."""
    result = CliRunner().invoke(
        app,
        [
            "rollback",
            "--feed",
            "f1-schedule-backup",
            "--year",
            "2026",
            "--from-state",
            str(tmp_path / "any.json"),
            "--out",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0


def test_rollback_requires_an_existing_snapshot(tmp_path: Path) -> None:
    """A missing snapshot is a parameter error, not a silent no-op."""
    result = CliRunner().invoke(
        app,
        [
            "rollback",
            "--feed",
            "f1-reports",
            "--year",
            "2026",
            "--from-state",
            str(tmp_path / "missing.json"),
            "--out",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert "snapshot not found" in result.output
