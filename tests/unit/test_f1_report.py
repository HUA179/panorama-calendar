"""Race report identity, revision chain and finality guards."""

from datetime import UTC, date, datetime, timedelta

import pytest

from panorama_calendar.models import (
    F1GridEntry,
    F1RaceReport,
    F1ResultEntry,
    F1Session,
    ResultStatus,
    SessionKind,
    SourceReference,
)
from panorama_calendar.pipelines import (
    F1ReportError,
    build_f1_report_events,
    build_f1_schedule_events,
)

RACE_DATE = date(2026, 11, 1)


def _source(url: str) -> SourceReference:
    """Return fixed retrieval evidence so fingerprints stay deterministic."""
    return SourceReference(
        url=url,
        authority="Formula 1",
        retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


def _report(
    *,
    status: ResultStatus = ResultStatus.FINAL,
    winner: str = "Max Verstappen",
    with_grid: bool = True,
    event_id: str = "mexico",
    name: str = "Mexico City Grand Prix",
) -> F1RaceReport:
    """Build one normalised report with a podium and a retirement."""
    grid = (
        [
            F1GridEntry(
                position=1,
                car_number="44",
                driver="Lewis Hamilton",
                team="Ferrari",
                time="1:16.514",
            ),
            F1GridEntry(
                position=2,
                car_number="1",
                driver="Max Verstappen",
                team="Red Bull Racing",
                time="1:16.601",
            ),
        ]
        if with_grid
        else []
    )
    return F1RaceReport(
        season=2026,
        event_id=event_id,
        grand_prix_name=name,
        official_name=f"FORMULA 1 {name.upper()} 2026",
        race_date=RACE_DATE,
        status=status,
        results=[
            F1ResultEntry(
                position="1",
                car_number="1",
                driver=winner,
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
            F1ResultEntry(
                position="3",
                car_number="12",
                driver="Kimi Antonelli",
                team="Mercedes",
                laps=71,
                time_or_status="+12.104",
                points=15,
            ),
            F1ResultEntry(
                position="NC",
                car_number="5",
                driver="Gabriel Bortoleto",
                team="Audi",
                laps=68,
                time_or_status="DNF",
                points=0,
            ),
        ],
        grid=grid,
        result_source=_source(
            "https://www.formula1.com/en/results/2026/races/1298/mexico/race-result"
        ),
        grid_source=(
            _source("https://www.formula1.com/en/results/2026/races/1298/mexico/starting-grid")
            if with_grid
            else None
        ),
        fia_classification_url=(
            "https://www.fia.com/system/files/decision-document/mexico_final.pdf"
            if status is not ResultStatus.PROVISIONAL
            else None
        ),
    )


def test_report_is_an_alarm_free_all_day_event() -> None:
    """A report never rings; it only records what happened."""
    event = build_f1_report_events([_report()])[0]
    assert event.alarms == []
    assert event.start_date == RACE_DATE
    assert event.end_date_exclusive == RACE_DATE + timedelta(days=1)
    assert event.transparent is True
    assert "战报" in event.categories


def test_report_identity_is_separate_from_the_schedule() -> None:
    """The same Grand Prix keeps two unrelated UIDs on two revision chains."""
    report_event = build_f1_report_events([_report()])[0]
    race_session = F1Session(
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
    schedule_event = build_f1_schedule_events([race_session])[0]
    assert report_event.uid != schedule_event.uid
    assert report_event.event_key == "report:2026:mexico"
    assert schedule_event.event_key != report_event.event_key


def test_report_renders_podium_pole_and_status_evidence() -> None:
    """The description answers who won, who started first, and how final it is."""
    event = build_f1_report_events([_report()])[0]
    assert event.summary == "F1战报｜Mexico City Grand Prix｜正赛"
    assert "状态：FIA 最终成绩" in event.description
    assert "冠军：Max Verstappen（Red Bull Racing，25 分）" in event.description
    assert "杆位：Lewis Hamilton（Ferrari，1:16.514）" in event.description
    assert "完赛：3 人；退赛：1 人" in event.description
    assert "FIA 最终成绩文件" in event.description
    assert "赛事：FORMULA 1 MEXICO CITY GRAND PRIX 2026" in event.description


def test_provisional_report_is_labelled_as_such() -> None:
    """Provisional results must never look final in the calendar."""
    event = build_f1_report_events([_report(status=ResultStatus.PROVISIONAL)])[0]
    assert event.summary.endswith("（暂定）")
    assert "以 FIA 最终成绩为准" in event.description
    assert event.result_status is ResultStatus.PROVISIONAL


def test_unchanged_report_does_not_advance_sequence() -> None:
    """Rebuilding identical facts must not bump SEQUENCE."""
    first = build_f1_report_events([_report()], now=datetime(2026, 11, 1, tzinfo=UTC))
    second = build_f1_report_events(
        [_report()], previous=first, now=datetime(2026, 11, 2, tzinfo=UTC)
    )
    assert second[0].sequence == first[0].sequence
    assert second[0].dtstamp == first[0].dtstamp


def test_amended_result_advances_sequence_without_uid_change() -> None:
    """A re-issued classification revises content only."""
    first = build_f1_report_events([_report()], now=datetime(2026, 11, 1, tzinfo=UTC))
    second = build_f1_report_events(
        [_report(status=ResultStatus.AMENDED, winner="Lewis Hamilton")],
        previous=first,
        now=datetime(2026, 11, 3, tzinfo=UTC),
    )
    assert second[0].uid == first[0].uid
    assert second[0].sequence == first[0].sequence + 1
    assert second[0].last_modified == datetime(2026, 11, 3, tzinfo=UTC)


def test_round_missing_from_a_build_is_retained() -> None:
    """A partial refresh of one Grand Prix keeps the rest of the feed."""
    previous = build_f1_report_events(
        [_report(), _report(event_id="brazil", name="São Paulo Grand Prix")]
    )
    refreshed = build_f1_report_events([_report()], previous=previous)
    assert len(refreshed) == 2
    assert {event.event_key for event in refreshed} == {
        "report:2026:mexico",
        "report:2026:brazil",
    }


def test_duplicate_rounds_in_one_build_are_rejected() -> None:
    """Two reports for one Grand Prix would silently drop a podium."""
    with pytest.raises(F1ReportError, match="duplicate report"):
        build_f1_report_events([_report(), _report()])


def test_finality_is_never_downgraded() -> None:
    """Losing the FIA document must not turn a final report provisional."""
    previous = build_f1_report_events([_report()])
    with pytest.raises(F1ReportError, match="refusing to downgrade"):
        build_f1_report_events([_report(status=ResultStatus.PROVISIONAL)], previous=previous)


def test_report_without_a_winner_is_rejected() -> None:
    """A classification missing P1 cannot represent a race."""
    with pytest.raises(ValueError, match="missing the winner"):
        F1RaceReport(
            season=2026,
            event_id="mexico",
            grand_prix_name="Mexico City Grand Prix",
            race_date=RACE_DATE,
            status=ResultStatus.FINAL,
            results=[
                F1ResultEntry(
                    position="2",
                    car_number="44",
                    driver="Lewis Hamilton",
                    team="Ferrari",
                    laps=71,
                    time_or_status="+8.271",
                    points=18,
                )
            ],
            result_source=_source("https://www.formula1.com/en/results/2026/races/1298/race-result"),
        )
