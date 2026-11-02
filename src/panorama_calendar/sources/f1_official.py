"""Authoritative Formula 1 schedule discovery and JSON-LD parsing."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from importlib.resources import files
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from panorama_calendar.models.enums import EventStatus, SessionKind
from panorama_calendar.models.f1 import F1Session
from panorama_calendar.models.source import SourceReference

F1_BASE_URL = "https://www.formula1.com"
_SESSION_FRAGMENTS = {
    "qualifying": SessionKind.QUALIFYING,
    "sprintqualifying": SessionKind.SPRINT_QUALIFYING,
    "sprint": SessionKind.SPRINT,
    "race": SessionKind.RACE,
}
_EVENT_STATUSES = {
    "https://schema.org/EventScheduled": EventStatus.CONFIRMED,
    "https://schema.org/EventRescheduled": EventStatus.CONFIRMED,
    "https://schema.org/EventPostponed": EventStatus.TENTATIVE,
    "https://schema.org/EventCancelled": EventStatus.CANCELLED,
}


class F1SourceError(RuntimeError):
    """Raised when official F1 markup cannot safely support a calendar build."""


class _F1MarkupParser(HTMLParser):
    """Collect racing links and JSON-LD blocks without executing page scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.json_scripts: list[str] = []
        self._in_json_ld = False
        self._json_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Collect only anchor targets and structured-data script bodies."""
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.links.append(str(attributes["href"]))
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self._in_json_ld = True
            self._json_parts = []

    def handle_data(self, data: str) -> None:
        """Accumulate a JSON-LD script body."""
        if self._in_json_ld:
            self._json_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Finish the current JSON-LD block."""
        if tag == "script" and self._in_json_ld:
            self.json_scripts.append("".join(self._json_parts))
            self._in_json_ld = False


def load_circuit_timezones() -> dict[str, str]:
    """Load the reviewed mapping from stable official slugs to IANA zones."""
    resource = files("panorama_calendar").joinpath("data/f1_circuits.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
    ):
        raise F1SourceError("F1 circuit timezone registry is malformed")
    return payload


def discover_f1_event_urls(index_html: str, season: int) -> list[str]:
    """Discover race detail pages while excluding preseason testing entries."""
    if "FIA Formula One World Championship" not in index_html or str(season) not in index_html:
        raise F1SourceError("F1 page is not the requested championship season")
    parser = _F1MarkupParser()
    parser.feed(index_html)
    prefix = f"/en/racing/{season}/"
    urls: list[str] = []
    for href in parser.links:
        absolute = urljoin(F1_BASE_URL, href).split("#", maxsplit=1)[0].split("?", maxsplit=1)[0]
        parsed = urlsplit(absolute)
        if parsed.scheme != "https" or parsed.netloc != "www.formula1.com":
            continue
        path = parsed.path.rstrip("/")
        if not path.startswith(prefix):
            continue
        event_id = path[len(prefix) :]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", event_id):
            continue
        if event_id.startswith("pre-season-testing"):
            continue
        url = f"{F1_BASE_URL}{path}"
        if url not in urls:
            urls.append(url)
    if not urls:
        raise F1SourceError("F1 season page yielded no race detail links")
    return urls


def _parse_timestamp(value: object, field: str) -> datetime:
    """Parse an official ISO timestamp and require an explicit offset."""
    if not isinstance(value, str) or not value:
        raise F1SourceError(f"F1 session is missing {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise F1SourceError(f"F1 session has invalid {field}: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise F1SourceError(f"F1 session {field} has no timezone offset")
    return parsed.astimezone(UTC)


def _session_kind(raw: dict[str, Any], event_url: str) -> SessionKind | None:
    """Map exact JSON-LD identifiers, never fuzzy title matching."""
    raw_id = raw.get("@id")
    if not isinstance(raw_id, str) or not raw_id.startswith(f"{event_url}#"):
        raise F1SourceError("F1 subevent has an invalid or foreign identifier")
    fragment = urlsplit(raw_id).fragment
    normalized = re.sub(r"[^a-z]", "", fragment.lower())
    if normalized in _SESSION_FRAGMENTS:
        return _SESSION_FRAGMENTS[normalized]
    if normalized.startswith(("practice", "testing")):
        return None
    raise F1SourceError(f"unknown F1 subevent identifier: {fragment}")


def _event_status(raw: dict[str, Any]) -> EventStatus:
    """Translate schema.org status without treating missing data as cancellation."""
    value = raw.get("eventStatus")
    if not isinstance(value, str) or value not in _EVENT_STATUSES:
        raise F1SourceError(f"unsupported F1 event status: {value!r}")
    return _EVENT_STATUSES[value]


def parse_f1_event_page(
    html: str,
    *,
    season: int,
    url: str,
    circuit_timezones: dict[str, str],
    retrieved_at: datetime | None = None,
) -> list[F1Session]:
    """Parse one official race detail page into whitelisted F1 sessions.

    Raises:
        F1SourceError: If identity, year, status, time or required sessions are invalid.
    """
    canonical_url = url.rstrip("/")
    event_id = canonical_url.rsplit("/", maxsplit=1)[-1]
    if event_id not in circuit_timezones:
        raise F1SourceError(f"no reviewed IANA timezone for F1 event: {event_id}")
    parser = _F1MarkupParser()
    parser.feed(html)
    roots: list[dict[str, Any]] = []
    for script in parser.json_scripts:
        try:
            payload = json.loads(script)
        except (json.JSONDecodeError, TypeError) as error:
            raise F1SourceError("F1 page contains invalid JSON-LD") from error
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if (
                isinstance(candidate, dict)
                and candidate.get("@type") == "SportsEvent"
                and str(candidate.get("@id", "")).rstrip("/") == canonical_url
            ):
                roots.append(candidate)
    if len(roots) != 1:
        raise F1SourceError("F1 page must contain exactly one matching SportsEvent JSON-LD")
    root = roots[0]
    subevents = root.get("subEvent")
    name = root.get("name")
    if not isinstance(subevents, list) or not isinstance(name, str) or not name:
        raise F1SourceError("F1 SportsEvent is missing its name or subevents")
    location_data = root.get("location")
    location = ""
    if isinstance(location_data, dict) and isinstance(location_data.get("name"), str):
        location = location_data["name"]
    source = SourceReference(
        url=canonical_url,
        authority="Formula 1",
        retrieved_at=retrieved_at or datetime.now(UTC),
        content_hash=hashlib.sha256(html.encode("utf-8")).hexdigest(),
    )
    sessions: list[F1Session] = []
    seen: set[SessionKind] = set()
    for raw in subevents:
        if not isinstance(raw, dict):
            raise F1SourceError("F1 subevent must be a JSON object")
        kind = _session_kind(raw, canonical_url)
        if kind is None:
            continue
        if kind in seen:
            raise F1SourceError(f"duplicate F1 session: {event_id} {kind.value}")
        seen.add(kind)
        try:
            session = F1Session(
                season=season,
                event_id=event_id,
                grand_prix_name=name,
                session_kind=kind,
                start_at_utc=_parse_timestamp(raw.get("startDate"), "startDate"),
                end_at_utc=(
                    _parse_timestamp(raw["endDate"], "endDate") if raw.get("endDate") else None
                ),
                circuit_timezone=circuit_timezones[event_id],
                location=location,
                status=_event_status(raw),
                source=source,
            )
        except ValueError as error:
            raise F1SourceError(f"invalid F1 session in {event_id}: {error}") from error
        sessions.append(session)
    if not {SessionKind.QUALIFYING, SessionKind.RACE}.issubset(seen):
        raise F1SourceError(f"F1 event {event_id} lacks qualifying or race data")
    return sessions


class F1OfficialClient:
    """Synchronous client for the official F1 season and race pages."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        """Inject an HTTP client for tests or create one with bounded timeouts."""
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Release HTTP resources."""
        self._client.close()

    def fetch_schedule(self, season: int) -> list[F1Session]:
        """Fetch every official race page; any source/schema failure propagates."""
        index_url = f"{F1_BASE_URL}/en/racing/{season}"
        response = self._client.get(index_url)
        response.raise_for_status()
        urls = discover_f1_event_urls(response.text, season)
        sessions: list[F1Session] = []
        timezones = load_circuit_timezones()
        for url in urls:
            detail = self._client.get(url)
            detail.raise_for_status()
            sessions.extend(
                parse_f1_event_page(
                    detail.text,
                    season=season,
                    url=url,
                    circuit_timezones=timezones,
                )
            )
        if not sessions:
            raise F1SourceError("official F1 schedule is empty")
        return sessions
