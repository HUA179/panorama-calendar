"""FIA decision documents: discover final classifications for status evidence.

The FIA documents index is server-rendered and filterable per Grand Prix.
We never parse the PDFs; the file names alone decide whether a race
classification is provisional, final, or re-issued after an amendment.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from html import unescape
from importlib.resources import files
from urllib.parse import unquote

import httpx

from panorama_calendar.models.enums import ResultStatus

FIA_BASE_URL = "https://www.fia.com"
_DOCUMENTS_ROOT_URL = f"{FIA_BASE_URL}/documents"


class FiaDocumentsError(RuntimeError):
    """Raised when FIA document discovery fails or changes structure."""


@dataclass(frozen=True, slots=True)
class FiaDocument:
    """One FIA decision document link."""

    name: str
    url: str


@dataclass(frozen=True, slots=True)
class FiaEventFilter:
    """One Grand Prix entry in the season documents filter."""

    label: str
    url: str


@dataclass(frozen=True, slots=True)
class FiaEventRegistry:
    """Reviewed slug-to-title mapping plus cross-source slug aliases."""

    events: dict[str, str]
    aliases: dict[str, str]

    def title_for(self, slug: str) -> str | None:
        """Resolve a schedule slug to its FIA event title, honouring aliases."""
        canonical = self.aliases.get(slug, slug)
        return self.events.get(canonical)


def load_fia_event_registry(season: int) -> FiaEventRegistry:
    """Load the reviewed registry for one season.

    Two official sites disagree on some slugs: the racing calendar calls the
    final round ``united-arab-emirates`` while the results pages call it
    ``abu-dhabi``. Aliases keep both pointing at one FIA document title
    instead of silently skipping the round.
    """
    resource = files("panorama_calendar").joinpath("data/f1_fia_events.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    season_payload = payload.get(str(season)) if isinstance(payload, dict) else None
    if not isinstance(season_payload, dict):
        raise FiaDocumentsError(f"no reviewed FIA event names for season {season}")
    events = season_payload.get("events")
    aliases = season_payload.get("aliases", {})
    if not isinstance(events, dict) or not events:
        raise FiaDocumentsError(f"FIA event name registry for {season} is empty")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in events.items()):
        raise FiaDocumentsError(f"FIA event names for {season} must be string pairs")
    if not isinstance(aliases, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in aliases.items()
    ):
        raise FiaDocumentsError(f"FIA event aliases for {season} must be string pairs")
    unknown_targets = sorted(set(aliases.values()) - set(events))
    if unknown_targets:
        raise FiaDocumentsError(f"FIA event aliases point at unknown slugs: {unknown_targets}")
    return FiaEventRegistry(events=dict(events), aliases=dict(aliases))


def find_documents_index(documents_page_html: str, season: int) -> str:
    """Locate the season documents index from the FIA documents entry page.

    ``/documents`` redirects to whichever season FIA currently highlights, but
    the redirected page always carries the full season selector, so the target
    season is discovered without hard-coding the numeric suffix. The selector
    is an ``<option value>`` list rather than anchors, hence both attributes.
    """
    pattern = re.compile(
        rf'(?:href|value)="((?:https://www\.fia\.com)?/documents/championships/[^"]*?'
        rf'/season/season-{season}-\d+)"'
    )
    matches = sorted(set(pattern.findall(documents_page_html)))
    if len(matches) != 1:
        raise FiaDocumentsError(
            f"expected exactly one FIA documents index for {season}, found {len(matches)}"
        )
    match = matches[0]
    return match if match.startswith("https://") else f"{FIA_BASE_URL}{match}"


def parse_event_documents(event_page_html: str) -> list[FiaDocument]:
    """Collect decision-document links from one Grand Prix documents page."""
    pattern = re.compile(r'href="(/system/files/decision-document/([^"]+\.pdf))"')
    documents: list[FiaDocument] = []
    seen: set[str] = set()
    for href, filename in pattern.findall(event_page_html):
        if href in seen:
            continue
        seen.add(href)
        documents.append(
            FiaDocument(name=unquote(filename), url=f"{FIA_BASE_URL}{href}")
        )
    return documents


def _ascii_key(name: str) -> str:
    """Normalise a document or event name for accent-insensitive matching."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()


def parse_event_filters(index_html: str) -> dict[str, FiaEventFilter]:
    """Map accent-folded Grand Prix labels to their documents URLs.

    FIA returns 500 for an unknown event filter, so the season index is the
    only safe way to ask "does this Grand Prix have documents yet?".
    """
    pattern = re.compile(r'<option value="([^"]*?/event/[^"]+)"[^>]*>([^<]*)</option>')
    filters: dict[str, FiaEventFilter] = {}
    for value, raw_label in pattern.findall(index_html):
        label = unescape(raw_label).strip()
        if not label:
            continue
        url = value if value.startswith("https://") else f"{FIA_BASE_URL}{value}"
        filters[_ascii_key(label)] = FiaEventFilter(label=label, url=url)
    return filters


def race_classification_status(
    documents: list[FiaDocument],
) -> tuple[ResultStatus, str | None]:
    """Derive the classification state from FIA document names.

    FINAL requires the published final classification; a re-issued final or
    an explicitly amended final marks AMENDED. PROVISIONAL is the safe
    default whenever only the provisional classification exists. No race
    classification at all means NOT_AVAILABLE.

    Amendment markers are only honoured on race-classification files. FIA also
    publishes unrelated amended documents (``curfew_amended``, entry lists),
    and treating those as a result change would relabel a clean race.
    """
    finals = [doc for doc in documents if "final_race_classification" in _ascii_key(doc.name)]
    provisionals = [
        doc for doc in documents if "provisional_race_classification" in _ascii_key(doc.name)
    ]
    reissued = [
        doc
        for doc in finals
        if "amended" in _ascii_key(doc.name)
        or re.search(r"final_race_classification_\d+", _ascii_key(doc.name))
    ]
    if finals:
        chosen = sorted(reissued or finals, key=lambda doc: doc.url)[-1]
        if reissued:
            return ResultStatus.AMENDED, chosen.url
        return ResultStatus.FINAL, chosen.url
    if provisionals:
        return ResultStatus.PROVISIONAL, sorted(doc.url for doc in provisionals)[-1]
    return ResultStatus.NOT_AVAILABLE, None


class FiaDocumentsClient:
    """Synchronous client for the FIA decision documents index."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        """Inject an HTTP client for tests or create one that follows redirects."""
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._index_cache: dict[int, str] = {}
        self._filter_cache: dict[int, dict[str, FiaEventFilter]] = {}

    def close(self) -> None:
        """Release HTTP resources."""
        self._client.close()

    def _get(self, url: str) -> str:
        """Fetch one FIA page and surface HTTP failures verbatim."""
        response = self._client.get(url)
        response.raise_for_status()
        return response.text

    def _documents_index(self, season: int) -> str:
        """Resolve and cache the season documents index URL."""
        if season not in self._index_cache:
            root = self._get(_DOCUMENTS_ROOT_URL)
            self._index_cache[season] = find_documents_index(root, season)
        return self._index_cache[season]

    def _event_filters(self, season: int) -> dict[str, FiaEventFilter]:
        """Resolve and cache the Grand Prix filter values for one season."""
        if season not in self._filter_cache:
            index = self._get(self._documents_index(season))
            filters = parse_event_filters(index)
            if not filters:
                raise FiaDocumentsError(f"FIA documents index for {season} lists no events")
            self._filter_cache[season] = filters
        return self._filter_cache[season]

    def has_event_documents(self, season: int, event_name: str) -> bool:
        """Report whether FIA has opened a documents folder for this Grand Prix."""
        return _ascii_key(event_name) in self._event_filters(season)

    def fetch_event_documents(self, season: int, event_name: str) -> list[FiaDocument]:
        """Fetch every decision document published for one Grand Prix.

        Returns an empty list when the event has no documents yet, which the
        status machine reports as NOT_AVAILABLE rather than an error.
        """
        match = self._event_filters(season).get(_ascii_key(event_name))
        if match is None:
            return []
        return parse_event_documents(self._get(match.url))
