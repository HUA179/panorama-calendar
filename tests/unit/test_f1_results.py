"""Official F1 results parsing: table shape, hidden driver codes, cheap failures."""

import httpx
import pytest

from panorama_calendar.sources.f1_results import (
    F1ResultsClient,
    F1ResultsError,
    discover_results_rounds,
    parse_race_result,
    parse_starting_grid,
    results_url_is_official,
)

RESULT_URL = "https://www.formula1.com/en/results/2026/races/1298/mexico/race-result"
GRID_URL = "https://www.formula1.com/en/results/2026/races/1298/mexico/starting-grid"

_RESULT_HEADER = (
    "<tr><th>Pos.</th><th>No.</th><th>Driver</th><th>Team</th>"
    "<th>Laps</th><th>Time / Retired</th><th>Pts.</th></tr>"
)
_GRID_HEADER = (
    "<tr><th>Pos.</th><th>No.</th><th>Driver</th><th>Team</th><th>Time</th></tr>"
)


def _result_row(
    position: str,
    number: str,
    first: str,
    last: str,
    code: str,
    team: str,
    laps: str,
    outcome: str,
    points: str,
) -> str:
    """Render one result row the way the official page does, code included."""
    return (
        f"<tr><td>{position}</td><td>{number}</td>"
        f'<td><span class="max-md:hidden">{first} </span>{last}'
        f'<span class="md:hidden">{code}</span></td>'
        f"<td>{team}</td><td>{laps}</td><td>{outcome}</td><td>{points}</td></tr>"
    )


def _result_page(rows: list[str]) -> str:
    """Wrap result rows in a table the parser can find."""
    return f"<html><table><tbody>{_RESULT_HEADER}{''.join(rows)}</tbody></table></html>"


def _grid_page(rows: list[str]) -> str:
    """Wrap starting-grid rows in a table the parser can find."""
    return f"<html><table><tbody>{_GRID_HEADER}{''.join(rows)}</tbody></table></html>"


def test_race_result_strips_the_hidden_driver_code() -> None:
    """The responsive three-letter code must never leak into the driver name."""
    html = _result_page(
        [
            _result_row(
                "1", "1", "Max", "Verstappen", "VER", "Red Bull Racing", "71", "1:37:58.574", "25"
            ),
            _result_row("2", "44", "Lewis", "Hamilton", "HAM", "Ferrari", "71", "+8.271", "18"),
            _result_row("NC", "5", "Gabriel", "Bortoleto", "BOR", "Audi", "68", "DNF", "0"),
        ]
    )
    parsed = parse_race_result(html, RESULT_URL)
    assert parsed is not None
    entries, source = parsed
    assert [entry.driver for entry in entries] == [
        "Max Verstappen",
        "Lewis Hamilton",
        "Gabriel Bortoleto",
    ]
    assert entries[0].points == 25
    assert entries[2].classified is False
    assert source.url == RESULT_URL
    assert len(source.content_hash or "") == 64


def test_missing_result_table_is_not_an_error() -> None:
    """A Grand Prix that has not finished yet yields None, not a crash."""
    placeholder = "<html><body><p>Results will appear after the race.</p></body></html>"
    assert parse_race_result(placeholder, RESULT_URL) is None
    assert parse_starting_grid(placeholder, GRID_URL) is None


def test_structurally_wrong_row_fails_closed() -> None:
    """A non-numeric lap count must not silently become zero."""
    html = _result_page(
        [
            _result_row(
                "1", "1", "Max", "Verstappen", "VER", "Red Bull Racing", "DNF", "1:37:58.574", "25"
            )
        ]
    )
    with pytest.raises(F1ResultsError, match="invalid race result row"):
        parse_race_result(html, RESULT_URL)


def test_driver_code_left_in_the_cell_is_rejected() -> None:
    """If FIA markup changes so the code is no longer hidden, stop loudly."""
    row = (
        "<tr><td>1</td><td>1</td><td>Max VerstappenVER</td>"
        "<td>Red Bull Racing</td><td>71</td><td>1:37:58.574</td><td>25</td></tr>"
    )
    with pytest.raises(F1ResultsError, match="unseparated code"):
        parse_race_result(_result_page([row]), RESULT_URL)


def test_starting_grid_parses_positions_and_times() -> None:
    """The grid keeps pole position and its qualifying time."""
    row = (
        '<tr><td>1</td><td>44</td><td>Lewis Hamilton<span class="md:hidden">HAM</span></td>'
        "<td>Ferrari</td><td>1:16.514</td></tr>"
    )
    parsed = parse_starting_grid(_grid_page([row]), GRID_URL)
    assert parsed is not None
    entries, source = parsed
    assert entries[0].position == 1
    assert entries[0].driver == "Lewis Hamilton"
    assert entries[0].time == "1:16.514"
    assert source.url == GRID_URL


def test_season_index_dedupes_and_keeps_discovery_order() -> None:
    """The filter dropdown repeats links; rounds must stay unique and ordered."""
    index = "".join(
        f'<a href="/en/results/2026/races/{race_id}/{slug}/race-result">x</a>'
        for race_id, slug in [
            (1287, "australia"),
            (1287, "australia"),
            (1298, "mexico"),
        ]
    )
    rounds = discover_results_rounds(index, 2026)
    assert [link.event_id for link in rounds] == ["australia", "mexico"]
    assert [link.round_number for link in rounds] == [1, 2]
    assert rounds[1].result_url == RESULT_URL


def test_season_index_without_links_fails_closed() -> None:
    """An empty or wrong-season page must not look like a finished season."""
    with pytest.raises(F1ResultsError, match="no race links"):
        discover_results_rounds("<html>2026</html>", 2026)
    with pytest.raises(F1ResultsError, match="not the requested season"):
        discover_results_rounds("<html>2025</html>", 2026)


def test_client_only_fetches_from_the_official_results_namespace() -> None:
    """A tampered link must be refused before any request is made."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="<html></html>", request=request)

    client = F1ResultsClient(httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        foreign = "https://evil.example/en/results/2026/races/1/mexico/race-result"
        assert results_url_is_official(foreign) is False
        with pytest.raises(F1ResultsError, match="refusing to fetch a foreign results URL"):
            client._get_text(foreign, 2026)
    finally:
        client.close()
    assert calls == []
