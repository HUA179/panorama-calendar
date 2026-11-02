"""Offline end-to-end build of the F1 report feed, including its revision state."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from panorama_calendar.cli import app
from panorama_calendar.ics import validate_ics_bytes
from panorama_calendar.models import (
    F1GridEntry,
    F1ResultEntry,
    F1Session,
    SessionKind,
    SourceReference,
)
from panorama_calendar.sources.f1_official import F1OfficialClient
from panorama_calendar.sources.f1_results import F1ResultsClient, F1RoundLink
from panorama_calendar.sources.fia_documents import FiaDocument, FiaDocumentsClient

RESULT_URL = "https://www.formula1.com/en/results/2026/races/1298/mexico/race-result"
GRID_URL = "https://www.formula1.com/en/results/2026/races/1298/mexico/starting-grid"


def _source(url: str) -> SourceReference:
    """Return fixed retrieval evidence."""
    return SourceReference(
        url=url, authority="Formula 1", retrieved_at=datetime(2026, 11, 1, tzinfo=UTC)
    )


def _wire_offline_sources(monkeypatch: object) -> None:
    """Replace every network adapter with deterministic official-shaped data."""
    session = F1Session(
        season=2026,
        event_id="mexico",
        grand_prix_name="FORMULA 1 GRAN PREMIO DE LA CIUDAD DE MÉXICO 2026",
        session_kind=SessionKind.RACE,
        start_at_utc=datetime(2026, 11, 1, 20, tzinfo=UTC),
        end_at_utc=datetime(2026, 11, 1, 22, tzinfo=UTC),
        circuit_timezone="America/Mexico_City",
        location="Mexico City",
        source=_source("https://www.formula1.com/en/racing/2026/mexico"),
    )
    link = F1RoundLink(season=2026, race_id=1298, event_id="mexico", round_number=20)
    results = [
        F1ResultEntry(
            position="1",
            car_number="1",
            driver="Max Verstappen",
            team="Red Bull Racing",
            laps=71,
            time_or_status="1:37:58.574",
            points=25,
        ),
        F1ResultEntry(
            position="2",
            car_number="44",
            driver="Lewis Hamilton",
            team="Ferrari",
            laps=71,
            time_or_status="+8.271",
            points=18,
        ),
    ]
    grid = [
        F1GridEntry(
            position=1, car_number="44", driver="Lewis Hamilton", team="Ferrari", time="1:16.514"
        )
    ]
    documents = [
        FiaDocument(
            name="2026_mexico_city_grand_prix_-_final_race_classification.pdf",
            url="https://www.fia.com/system/files/decision-document/mexico_final.pdf",
        )
    ]
    monkeypatch.setattr(F1OfficialClient, "fetch_schedule", lambda self, year: [session])  # type: ignore[attr-defined]
    monkeypatch.setattr(F1ResultsClient, "fetch_round_links", lambda self, year: [link])  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        F1ResultsClient,
        "fetch_race_result",
        lambda self, round_link: (results, _source(RESULT_URL)),
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        F1ResultsClient,
        "fetch_starting_grid",
        lambda self, round_link: (grid, _source(GRID_URL)),
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        FiaDocumentsClient,
        "fetch_event_documents",
        lambda self, season, event_name: documents,
    )


def test_f1_report_cli_writes_an_alarm_free_feed_and_state(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """The documented command produces a valid feed plus a revision snapshot."""
    _wire_offline_sources(monkeypatch)
    result = CliRunner().invoke(app, ["f1-report", "--year", "2026", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output

    data = (tmp_path / "f1-reports-2026.ics").read_bytes()
    validate_ics_bytes(data)
    assert data.count(b"BEGIN:VEVENT") == 1
    assert b"BEGIN:VALARM" not in data
    assert b"DTSTART;VALUE=DATE:20261101" in data
    assert "FIA 最终成绩".encode() in data
    state = tmp_path / "f1-reports-2026.state.json"
    assert state.is_file()
    assert "report:2026:mexico" in state.read_text(encoding="utf-8")


def test_second_run_reuses_the_same_uid_and_sequence(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Rebuilding identical facts is a no-op for subscribers."""
    _wire_offline_sources(monkeypatch)
    runner = CliRunner()
    first = runner.invoke(app, ["f1-report", "--year", "2026", "--out", str(tmp_path)])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["f1-report", "--year", "2026", "--out", str(tmp_path)])
    assert second.exit_code == 0, second.output

    data = (tmp_path / "f1-reports-2026.ics").read_bytes()
    assert data.count(b"SEQUENCE:0") == 1
    uids = [line for line in data.splitlines() if line.startswith(b"UID:")]
    assert len(uids) == 1


def test_lost_state_continues_from_the_published_feed(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """A wiped snapshot must not restart the feed at SEQUENCE 0."""
    _wire_offline_sources(monkeypatch)
    runner = CliRunner()
    first = runner.invoke(app, ["f1-report", "--year", "2026", "--out", str(tmp_path)])
    assert first.exit_code == 0, first.output
    (tmp_path / "f1-reports-2026.state.json").unlink()

    second = runner.invoke(app, ["f1-report", "--year", "2026", "--out", str(tmp_path)])

    assert second.exit_code == 0, second.output
    data = (tmp_path / "f1-reports-2026.ics").read_bytes()
    assert b"SEQUENCE:0" not in data
    assert b"SEQUENCE:1" in data


def test_publication_is_recorded_in_the_audit_trail(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Each successful write leaves one line explaining what changed."""
    _wire_offline_sources(monkeypatch)
    result = CliRunner().invoke(app, ["f1-report", "--year", "2026", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output

    trail = (tmp_path / "f1-reports-2026.revisions.jsonl").read_text(encoding="utf-8")

    assert '"action": "build"' in trail
    assert '"events": 1' in trail
    assert '"sequence_max": 0' in trail


def test_future_rounds_are_skipped_without_touching_the_feed(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """A race that has not run yet is not a build failure."""
    _wire_offline_sources(monkeypatch)
    upcoming = F1Session(
        season=2026,
        event_id="brazil",
        grand_prix_name="FORMULA 1 SAO PAULO GRAND PRIX 2026",
        session_kind=SessionKind.RACE,
        start_at_utc=datetime.now(UTC) + timedelta(days=6),
        end_at_utc=datetime.now(UTC) + timedelta(days=6, hours=2),
        circuit_timezone="America/Sao_Paulo",
        location="São Paulo",
        source=_source("https://www.formula1.com/en/racing/2026/brazil"),
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        F1OfficialClient, "fetch_schedule", lambda self, year: [upcoming]
    )
    result = CliRunner().invoke(
        app, ["f1-report", "--year", "2026", "--event", "brazil", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "has not run yet" in result.output
    assert not (tmp_path / "f1-reports-2026.ics").exists()
