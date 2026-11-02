"""Golden samples for official F1 discovery and JSON-LD parsing."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from panorama_calendar.models import SessionKind
from panorama_calendar.sources.f1_official import (
    F1SourceError,
    discover_f1_event_urls,
    parse_f1_event_page,
)

URL = "https://www.formula1.com/en/racing/2026/brazil"
_DEFAULT_START = object()


def _event_page(*, drop_race: bool = False, start_date: object = _DEFAULT_START) -> str:
    """Return a compact official-shaped event with practice and sprint sessions."""

    def subevent(fragment: str, start: object) -> dict[str, object]:
        return {
            "@type": "SportsEvent",
            "@id": f"{URL}#{fragment}",
            "name": fragment,
            "startDate": start,
            "endDate": "2026-11-08T19:00:00.000Z",
            "eventStatus": "https://schema.org/EventScheduled",
        }

    subevents = [
        subevent("Practice-1", "2026-11-06T15:30:00.000Z"),
        subevent("SprintQualifying", "2026-11-06T18:30:00.000Z"),
        subevent("Sprint", "2026-11-07T14:00:00.000Z"),
        subevent("Qualifying", "2026-11-07T18:00:00.000Z"),
    ]
    if not drop_race:
        race_start = (
            "2026-11-08T17:00:00.000Z" if start_date is _DEFAULT_START else start_date
        )
        subevents.append(subevent("Race", race_start))
    payload = {
        "@type": "SportsEvent",
        "@id": URL,
        "name": "FORMULA 1 GRANDE PRÊMIO DE SÃO PAULO 2026",
        "location": {"@type": "City", "name": "São Paulo"},
        "subEvent": subevents,
    }
    return f'<html><script type="application/ld+json">{json.dumps(payload)}</script></html>'


def test_parse_official_page_keeps_only_whitelisted_sessions() -> None:
    """Practice disappears while sprint qualifying remains distinct."""
    sessions = parse_f1_event_page(
        _event_page(),
        season=2026,
        url=URL,
        circuit_timezones={"brazil": "America/Sao_Paulo"},
        retrieved_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    assert [item.session_kind for item in sessions] == [
        SessionKind.SPRINT_QUALIFYING,
        SessionKind.SPRINT,
        SessionKind.QUALIFYING,
        SessionKind.RACE,
    ]
    assert sessions[-1].start_at_utc == datetime(2026, 11, 8, 17, tzinfo=UTC)
    assert sessions[-1].event_key == "f1:session:2026:brazil:RACE"
    assert sessions[-1].source.url == URL


@pytest.mark.parametrize("start", [None, "2026-11-08T17:00:00"])
def test_missing_or_naive_official_time_is_rejected(start: object) -> None:
    """No midnight is invented for absent or timezone-less official times."""
    with pytest.raises(F1SourceError, match="startDate"):
        parse_f1_event_page(
            _event_page(start_date=start),
            season=2026,
            url=URL,
            circuit_timezones={"brazil": "America/Sao_Paulo"},
        )


def test_incomplete_event_is_rejected_instead_of_partially_published() -> None:
    """A missing race record fails closed rather than publishing half an event."""
    with pytest.raises(F1SourceError, match="lacks qualifying or race"):
        parse_f1_event_page(
            _event_page(drop_race=True),
            season=2026,
            url=URL,
            circuit_timezones={"brazil": "America/Sao_Paulo"},
        )


def test_season_discovery_excludes_testing_and_foreign_links() -> None:
    """Only unique same-season official race links become fetch targets."""
    html = """
    <html><title>2026 FIA Formula One World Championship</title>
    <a href="/en/racing/2026/brazil">Brazil</a>
    <a href="https://www.formula1.com/en/racing/2026/brazil#top">Again</a>
    <a href="/en/racing/2026/pre-season-testing-1">Testing</a>
    <a href="https://example.com/en/racing/2026/fake">Foreign</a>
    </html>
    """
    assert discover_f1_event_urls(html, 2026) == [URL]
