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
MEXICO_RESULT_URL = "https://www.formula1.com/en/results/2026/races/1298/mexico/race-result"
MEXICO_QUALIFYING_URL = "https://www.formula1.com/en/results/2026/races/1298/mexico/qualifying"
MEXICO_SPRINT_URL = "https://www.formula1.com/en/results/2026/races/1298/mexico/sprint-results"
MEXICO_SPRINT_Q_URL = (
    "https://www.formula1.com/en/results/2026/races/1298/mexico/sprint-qualifying"
)


def _source(url: str) -> SourceReference:
    """Return fixed retrieval evidence so fingerprints stay deterministic."""
    return SourceReference(
        url=url,
        authority="Formula 1",
        retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


def _podium(winner: str = "Max Verstappen") -> list[F1ResultEntry]:
    """Return one classified podium plus a retirement."""
    return [
        F1ResultEntry(
            position="1",
            car_number="3",
            driver=winner,
            code="VER",
            team="Red Bull Racing",
            laps=71,
            time_or_status="1:37:58.574",
            points=25,
        ),
        F1ResultEntry(
            position="2",
            car_number="44",
            driver="Lewis Hamilton",
            code="HAM",
            team="Ferrari",
            laps=71,
            time_or_status="+8.271",
            points=18,
        ),
        F1ResultEntry(
            position="3",
            car_number="12",
            driver="Kimi Antonelli",
            code="ANT",
            team="Mercedes",
            laps=71,
            time_or_status="+12.104",
            points=15,
        ),
        F1ResultEntry(
            position="NC",
            car_number="5",
            driver="Gabriel Bortoleto",
            code="BOR",
            team="Audi",
            laps=68,
            time_or_status="DNF",
            points=0,
        ),
    ]


def _report(
    *,
    status: ResultStatus = ResultStatus.FINAL,
    winner: str = "Max Verstappen",
    with_pole: bool = True,
    with_sprint: bool = False,
    event_id: str = "mexico",
    name: str = "Mexico City Grand Prix",
) -> F1RaceReport:
    """Build one normalised report with a podium, a pole and a retirement."""
    pole = (
        F1GridEntry(
            position=1,
            car_number="16",
            driver="Charles Leclerc",
            code="LEC",
            team="Ferrari",
            time="1:16.514",
        )
        if with_pole
        else None
    )
    sprint_results: list[F1ResultEntry] = []
    sprint_pole = None
    if with_sprint:
        sprint_results = [
            F1ResultEntry(
                position="1",
                car_number="1",
                driver="Lando Norris",
                code="NOR",
                team="McLaren",
                laps=24,
                time_or_status="39:12.004",
                points=8,
            ),
            F1ResultEntry(
                position="2",
                car_number="81",
                driver="Oscar Piastri",
                code="PIA",
                team="McLaren",
                laps=24,
                time_or_status="+1.882",
                points=7,
            ),
            F1ResultEntry(
                position="3",
                car_number="3",
                driver="Max Verstappen",
                code="VER",
                team="Red Bull Racing",
                laps=24,
                time_or_status="+4.310",
                points=6,
            ),
        ]
        sprint_pole = F1GridEntry(
            position=1,
            car_number="1",
            driver="Lando Norris",
            code="NOR",
            team="McLaren",
            time="1:15.882",
        )
    return F1RaceReport(
        season=2026,
        event_id=event_id,
        grand_prix_name=name,
        official_name=f"FORMULA 1 {name.upper()} 2026",
        race_date=RACE_DATE,
        status=status,
        results=_podium(winner),
        result_source=_source(MEXICO_RESULT_URL),
        pole=pole,
        pole_source=_source(MEXICO_QUALIFYING_URL) if with_pole else None,
        sprint_results=sprint_results,
        sprint_source=_source(MEXICO_SPRINT_URL) if with_sprint else None,
        sprint_pole=sprint_pole,
        sprint_pole_source=_source(MEXICO_SPRINT_Q_URL) if with_sprint else None,
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


def test_report_renders_the_strict_description_template() -> None:
    """The description follows the agreed line-by-line layout."""
    event = build_f1_report_events([_report()])[0]
    assert event.summary == "F1战报｜Mexico City Grand Prix｜正赛"
    assert event.description == (
        "状态：FIA 最终成绩\n"
        "赛事：FORMULA 1 MEXICO CITY GRAND PRIX 2026\n"
        "【正赛】\n"
        "杆位：16 LEC 勒克莱尔 🇲🇨 Charles Leclerc (Ferrari, 1:16.514)\n"
        "成绩：\n"
        "🏅 P1 3 VER 维斯塔潘 🇳🇱 Max Verstappen (Red Bull Racing)\n"
        "🥈 P2 44 HAM 汉密尔顿 🇬🇧 Lewis Hamilton (Ferrari)\n"
        "🥉 P3 12 ANT 安东内利 🇮🇹 Kimi Antonelli (Mercedes)\n"
        "完赛：3 人；退赛：1 人\n"
        f"来源：{MEXICO_RESULT_URL}"
    )


def test_sprint_weekend_report_merges_both_classifications() -> None:
    """A sprint round carries the sprint block between the header and the race."""
    event = build_f1_report_events([_report(with_sprint=True)])[0]
    lines = event.description.splitlines()
    assert lines == [
        "状态：FIA 最终成绩",
        "赛事：FORMULA 1 MEXICO CITY GRAND PRIX 2026",
        "【冲刺赛】",
        "杆位：1 NOR 诺里斯 🇬🇧 Lando Norris (McLaren, 1:15.882)",
        "成绩：",
        "🏅 P1 1 NOR 诺里斯 🇬🇧 Lando Norris (McLaren)",
        "🥈 P2 81 PIA 皮亚斯特里 🇦🇺 Oscar Piastri (McLaren)",
        "🥉 P3 3 VER 维斯塔潘 🇳🇱 Max Verstappen (Red Bull Racing)",
        "【正赛】",
        "杆位：16 LEC 勒克莱尔 🇲🇨 Charles Leclerc (Ferrari, 1:16.514)",
        "成绩：",
        "🏅 P1 3 VER 维斯塔潘 🇳🇱 Max Verstappen (Red Bull Racing)",
        "🥈 P2 44 HAM 汉密尔顿 🇬🇧 Lewis Hamilton (Ferrari)",
        "🥉 P3 12 ANT 安东内利 🇮🇹 Kimi Antonelli (Mercedes)",
        "完赛：3 人；退赛：1 人",
        f"来源：{MEXICO_RESULT_URL}",
    ]


def test_unmapped_driver_code_degrades_without_translation() -> None:
    """A newcomer without a registry entry keeps number, code and English name."""
    report = _report()
    report.results[0] = report.results[0].model_copy(update={"code": "XXX"})
    event = build_f1_report_events([report])[0]
    assert "🏅 P1 3 XXX Max Verstappen (Red Bull Racing)" in event.description


def test_pole_without_a_lap_time_omits_the_time() -> None:
    """A missing segment time never renders a trailing comma."""
    report = _report()
    report.pole = report.pole.model_copy(update={"time": ""}) if report.pole else None
    event = build_f1_report_events([report])[0]
    assert "杆位：16 LEC 勒克莱尔 🇲🇨 Charles Leclerc (Ferrari)" in event.description


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
                    code="HAM",
                    team="Ferrari",
                    laps=71,
                    time_or_status="+8.271",
                    points=18,
                )
            ],
            result_source=_source(MEXICO_RESULT_URL),
        )


def test_sprint_classification_is_validated_like_the_race() -> None:
    """A sprint table without a winner cannot pass as a sprint weekend."""
    with pytest.raises(ValueError, match="sprint results are missing the winner"):
        F1RaceReport(
            season=2026,
            event_id="mexico",
            grand_prix_name="Mexico City Grand Prix",
            race_date=RACE_DATE,
            status=ResultStatus.FINAL,
            results=_podium(),
            result_source=_source(MEXICO_RESULT_URL),
            sprint_results=[
                F1ResultEntry(
                    position="2",
                    car_number="81",
                    driver="Oscar Piastri",
                    code="PIA",
                    team="McLaren",
                    laps=24,
                    time_or_status="+1.882",
                    points=7,
                )
            ],
            sprint_source=_source(MEXICO_SPRINT_URL),
        )


def test_sprint_facts_require_their_sources() -> None:
    """Sprint rows without retrieval evidence are rejected outright."""
    with pytest.raises(ValueError, match="sprint results require a retrieval source"):
        F1RaceReport(
            season=2026,
            event_id="mexico",
            grand_prix_name="Mexico City Grand Prix",
            race_date=RACE_DATE,
            status=ResultStatus.FINAL,
            results=_podium(),
            result_source=_source(MEXICO_RESULT_URL),
            sprint_results=_report(with_sprint=True).sprint_results,
        )
