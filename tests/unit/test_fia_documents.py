"""FIA document discovery: season index, event filters and finality states."""

import httpx
import pytest

from panorama_calendar.models.enums import ResultStatus
from panorama_calendar.sources.fia_documents import (
    FiaDocument,
    FiaDocumentsClient,
    FiaDocumentsError,
    find_documents_index,
    load_fia_event_registry,
    parse_event_documents,
    parse_event_filters,
    race_classification_status,
)

SEASON = 2026
ROOT_URL = "https://www.fia.com/documents"
INDEX_PATH = (
    "/documents/championships/fia-formula-one-world-championship-14"
    "/season/season-2026-2072"
)
INDEX_URL = f"https://www.fia.com{INDEX_PATH}"


def _root_page(*season_ids: str) -> str:
    """Render the season selector the documents entry page redirects to."""
    options = "".join(
        f'<option value="/documents/championships/fia-formula-one-world-championship-14'
        f'/season/season-{item}">SEASON {item.split("-")[0]}</option>'
        for item in season_ids
    )
    return f'<html><select id="facetapi_select_facet_form_3">{options}</select></html>'


def _index_page(*events: str) -> str:
    """Render the Grand Prix filter of a season documents index."""
    options = "".join(
        f'<option value="{INDEX_PATH}/event/{event.replace(" ", "%20")}">{event}</option>'
        for event in events
    )
    return f'<html><select id="facetapi_select_facet_form_4">{options}</select></html>'


def _event_page(*names: str) -> str:
    """Render one Grand Prix documents folder."""
    links = "".join(
        f'<a href="/system/files/decision-document/{name}">{name}</a>' for name in names
    )
    return f"<html><table>{links}</table></html>"


def test_documents_index_is_discovered_from_the_season_selector() -> None:
    """The target season is read from the selector, not hard-coded."""
    root = _root_page("2025-2071", "2026-2072")
    assert find_documents_index(root, SEASON) == INDEX_URL


def test_missing_or_ambiguous_season_index_fails_closed() -> None:
    """Zero or two candidates means the site changed; refuse to guess."""
    with pytest.raises(FiaDocumentsError, match="found 0"):
        find_documents_index(_root_page("2025-2071"), SEASON)
    duplicated = _root_page("2026-2072")
    duplicated += '<a href="/documents/championships/other/season/season-2026-9999">x</a>'
    with pytest.raises(FiaDocumentsError, match="found 2"):
        find_documents_index(duplicated, SEASON)


def test_event_filters_ignore_accents() -> None:
    """FIA may spell an event with or without diacritics; both must resolve."""
    filters = parse_event_filters(_index_page("São Paulo Grand Prix", "Mexico City Grand Prix"))
    assert set(filters) == {"sao paulo grand prix", "mexico city grand prix"}
    assert filters["mexico city grand prix"].url.endswith("/event/Mexico%20City%20Grand%20Prix")


def test_document_links_are_absolute_and_decoded() -> None:
    """PDF names are stored decoded while URLs keep the original encoding."""
    documents = parse_event_documents(
        _event_page("2026_mexico_city_grand_prix_-_final_race_classification.pdf")
    )
    assert len(documents) == 1
    assert documents[0].name == "2026_mexico_city_grand_prix_-_final_race_classification.pdf"
    assert documents[0].url.startswith("https://www.fia.com/system/files/decision-document/")


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ([], ResultStatus.NOT_AVAILABLE),
        (["2026_x_-_provisional_race_classification.pdf"], ResultStatus.PROVISIONAL),
        (
            [
                "2026_x_-_provisional_race_classification.pdf",
                "2026_x_-_final_race_classification.pdf",
            ],
            ResultStatus.FINAL,
        ),
        (
            [
                "2026_x_-_final_race_classification.pdf",
                "2026_x_-_amended_final_race_classification.pdf",
            ],
            ResultStatus.AMENDED,
        ),
    ],
)
def test_classification_status_follows_published_documents(
    names: list[str],
    expected: ResultStatus,
) -> None:
    """Only the published file names decide finality."""
    documents = [
        FiaDocument(name=name, url=f"https://www.fia.com/system/files/decision-document/{name}")
        for name in names
    ]
    status, url = race_classification_status(documents)
    assert status is expected
    assert (url is None) is (expected is ResultStatus.NOT_AVAILABLE)


def test_practice_documents_never_count_as_a_race_classification() -> None:
    """Free practice files must not promote a race to provisional."""
    documents = [
        FiaDocument(
            name="2026_x_-_free_practice_1_classification.pdf",
            url="https://www.fia.com/system/files/decision-document/fp1.pdf",
        )
    ]
    status, url = race_classification_status(documents)
    assert status is ResultStatus.NOT_AVAILABLE
    assert url is None


def test_unrelated_amended_documents_do_not_relabel_a_result() -> None:
    """A curfew waiver is not a result change and must stay FINAL."""
    documents = [
        FiaDocument(
            name="2026_azerbaijan_grand_prix_-_final_race_classification.pdf",
            url="https://www.fia.com/system/files/decision-document/final.pdf",
        ),
        FiaDocument(
            name="2026_azerbaijan_grand_prix_-_curfew_amended.pdf",
            url="https://www.fia.com/system/files/decision-document/curfew_amended.pdf",
        ),
    ]
    status, url = race_classification_status(documents)
    assert status is ResultStatus.FINAL
    assert url == "https://www.fia.com/system/files/decision-document/final.pdf"


def test_reissued_final_points_at_the_new_file() -> None:
    """A numbered re-issue must link to the re-issued document, not the first."""
    documents = [
        FiaDocument(
            name="2026_x_-_final_race_classification.pdf",
            url="https://www.fia.com/system/files/decision-document/final.pdf",
        ),
        FiaDocument(
            name="2026_x_-_final_race_classification_2.pdf",
            url="https://www.fia.com/system/files/decision-document/final_2.pdf",
        ),
    ]
    status, url = race_classification_status(documents)
    assert status is ResultStatus.AMENDED
    assert url == "https://www.fia.com/system/files/decision-document/final_2.pdf"


def test_registry_resolves_cross_site_slug_aliases() -> None:
    """The racing calendar and results pages disagree on the final round."""
    registry = load_fia_event_registry(2026)
    assert registry.title_for("united-arab-emirates") == "Abu Dhabi Grand Prix"
    assert registry.title_for("abu-dhabi") == "Abu Dhabi Grand Prix"
    assert registry.title_for("brazil") == "São Paulo Grand Prix"
    assert registry.title_for("nowhere") is None


def test_client_skips_events_without_a_documents_folder() -> None:
    """FIA answers 500 for unknown filters, so absence is decided offline."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == ROOT_URL:
            return httpx.Response(200, text=_root_page("2026-2072"), request=request)
        if str(request.url) == INDEX_URL:
            return httpx.Response(
                200,
                text=_index_page("Mexico City Grand Prix", "São Paulo Grand Prix"),
                request=request,
            )
        if str(request.url).endswith("/event/Mexico%20City%20Grand%20Prix"):
            return httpx.Response(
                200,
                text=_event_page("2026_mexico_city_grand_prix_-_final_race_classification.pdf"),
                request=request,
            )
        return httpx.Response(500, text="server error", request=request)

    client = FiaDocumentsClient(httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        documents = client.fetch_event_documents(2026, "Mexico City Grand Prix")
        assert len(documents) == 1
        assert race_classification_status(documents)[0] is ResultStatus.FINAL
        assert client.has_event_documents(2026, "Sao Paulo Grand Prix") is True
        assert client.fetch_event_documents(2026, "Qatar Grand Prix") == []
    finally:
        client.close()
    assert not any("Qatar" in url for url in requested)
