"""Offline end-to-end build of the official F1 schedule feed."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from panorama_calendar.cli import app
from panorama_calendar.ics import validate_ics_bytes
from panorama_calendar.models import F1Session, SessionKind, SourceReference
from panorama_calendar.sources.f1_official import F1OfficialClient
from panorama_calendar.sources.jolpica import JolpicaClient


def test_f1_schedule_cli_writes_valid_utc_feed(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """The network adapter is replaced; generation and byte validation stay real."""
    session = F1Session(
        season=2026,
        event_id="brazil",
        grand_prix_name="São Paulo Grand Prix 2026",
        session_kind=SessionKind.RACE,
        start_at_utc=datetime(2026, 11, 8, 17, tzinfo=UTC),
        end_at_utc=datetime(2026, 11, 8, 17, tzinfo=UTC) + timedelta(hours=2),
        circuit_timezone="America/Sao_Paulo",
        source=SourceReference(
            url="https://www.formula1.com/en/racing/2026/brazil",
            authority="Formula 1",
            retrieved_at=datetime(2026, 11, 2, tzinfo=UTC),
        ),
    )
    monkeypatch.setattr(F1OfficialClient, "fetch_schedule", lambda self, year: [session])
    monkeypatch.setattr(JolpicaClient, "fetch_schedule_or_none", lambda self, year: None)
    result = CliRunner().invoke(app, ["f1-schedule", "--year", "2026", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    data = (tmp_path / "f1-schedule-2026.ics").read_bytes()
    validate_ics_bytes(data)
    assert data.count(b"BEGIN:VEVENT") == 1
    assert b"DTSTART:20261108T170000Z" in data
    assert b"DTEND:20261108T190000Z" in data
    assert b"BEGIN:VALARM" not in data
    unfolded = data.decode("utf-8").replace("\r\n ", "").replace("\\,", ",")
    assert "🏎️ 巴西大奖赛（圣保罗, São Paulo） | 正赛" in unfolded
