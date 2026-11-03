"""Official Formula 1 race results and starting grid parsing.

The results pages are server-rendered tables. Driver cells hide the three
letter code inside a responsive ``md:hidden`` span, so the table parser
suppresses those spans instead of relying on fragile name trimming.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from panorama_calendar.models.f1 import F1GridEntry, F1QualifyingEntry, F1ResultEntry
from panorama_calendar.models.source import SourceReference

F1_BASE_URL = "https://www.formula1.com"
RACE_RESULT_HEADER = ["Pos.", "No.", "Driver", "Team", "Laps", "Time / Retired", "Pts."]
STARTING_GRID_HEADER = ["Pos.", "No.", "Driver", "Team", "Time"]
QUALIFYING_HEADER = ["Pos.", "No.", "Driver", "Team", "Q1", "Q2", "Q3", "Laps"]
_DRIVER_COLUMN = 2
_DRIVER_CODE_PATTERN = re.compile(r".*[a-z][A-Z]{3}$")


class F1ResultsError(RuntimeError):
    """Raised when official results markup cannot safely support a report."""


@dataclass(frozen=True, slots=True)
class F1RoundLink:
    """One Grand Prix entry discovered on the season results index."""

    season: int
    race_id: int
    event_id: str
    round_number: int

    @property
    def result_url(self) -> str:
        """Return the official race classification URL."""
        return (
            f"{F1_BASE_URL}/en/results/{self.season}/races/{self.race_id}"
            f"/{self.event_id}/race-result"
        )

    @property
    def grid_url(self) -> str:
        """Return the official starting grid URL."""
        return (
            f"{F1_BASE_URL}/en/results/{self.season}/races/{self.race_id}"
            f"/{self.event_id}/starting-grid"
        )

    @property
    def qualifying_url(self) -> str:
        """Return the official qualifying classification URL."""
        return (
            f"{F1_BASE_URL}/en/results/{self.season}/races/{self.race_id}"
            f"/{self.event_id}/qualifying"
        )

    @property
    def sprint_results_url(self) -> str:
        """Return the official sprint classification URL."""
        return (
            f"{F1_BASE_URL}/en/results/{self.season}/races/{self.race_id}"
            f"/{self.event_id}/sprint-results"
        )

    @property
    def sprint_qualifying_url(self) -> str:
        """Return the official sprint qualifying classification URL."""
        return (
            f"{F1_BASE_URL}/en/results/{self.season}/races/{self.race_id}"
            f"/{self.event_id}/sprint-qualifying"
        )


class _ResultsTableParser(HTMLParser):
    """Collect table rows, keeping the hidden driver codes alongside.

    The visible text of a cell lands in ``rows`` while the text hidden by
    responsive spans lands in ``codes`` at the same row/column position, so
    the driver column can be read as a name plus its three-letter code.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.codes: list[list[str]] = []
        self._in_cell = False
        self._cell: list[str] = []
        self._hidden: list[str] = []
        self._spans: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track rows, cells, and the spans that hide driver codes."""
        if tag == "tr":
            self.rows.append([])
            self.codes.append([])
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell = []
            self._hidden = []
            self._spans = []
        elif tag == "span" and self._in_cell:
            classes = dict(attrs).get("class") or ""
            # Name parts are hidden on large screens; the code is hidden on
            # medium screens. Order matters: "max-md:hidden" contains "md:hidden".
            suppress = (
                "max-lg:hidden" not in classes
                and "max-md:hidden" not in classes
                and "md:hidden" in classes
            )
            self._spans.append(suppress)

    def handle_data(self, data: str) -> None:
        """Split visible text from the suppressed driver-code text."""
        if not self._in_cell:
            return
        if any(self._spans):
            self._hidden.append(data)
        else:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Finalize spans, cells, and rows in reverse order."""
        if tag == "span" and self._in_cell and self._spans:
            self._spans.pop()
        elif tag in ("td", "th") and self._in_cell:
            self.rows[-1].append(" ".join("".join(self._cell).split()))
            self.codes[-1].append("".join(self._hidden).strip())
            self._in_cell = False


def discover_results_rounds(index_html: str, season: int) -> list[F1RoundLink]:
    """Discover race result links in calendar order from the season index."""
    if str(season) not in index_html:
        raise F1ResultsError("F1 results page is not the requested season")
    pattern = re.compile(rf"/en/results/{season}/races/(\d+)/([a-z0-9-]+)/race-result")
    rounds: list[F1RoundLink] = []
    seen: set[str] = set()
    for race_id, event_id in pattern.findall(index_html):
        if event_id in seen:
            continue
        seen.add(event_id)
        rounds.append(
            F1RoundLink(
                season=season,
                race_id=int(race_id),
                event_id=event_id,
                round_number=len(rounds) + 1,
            )
        )
    if not rounds:
        raise F1ResultsError("F1 results season page yielded no race links")
    return rounds


def _extract_table(
    html: str, header: list[str], url: str
) -> tuple[list[list[str]], list[str]] | None:
    """Return data rows plus their driver codes, or None when the table is absent."""
    parser = _ResultsTableParser()
    parser.feed(html)
    start = None
    for index, row in enumerate(parser.rows):
        if row == header:
            start = index + 1
            break
    if start is None:
        return None
    rows: list[list[str]] = []
    codes: list[str] = []
    for row, hidden in zip(parser.rows[start:], parser.codes[start:], strict=True):
        if len(row) != len(header):
            break
        rows.append(row)
        codes.append(hidden[_DRIVER_COLUMN] if len(hidden) > _DRIVER_COLUMN else "")
    if not rows:
        return [], []
    if any(any("javascript:" in cell.lower() for cell in row) for row in rows):
        raise F1ResultsError(f"F1 results table contains script content: {url}")
    return rows, codes


def _driver_name(value: str, url: str) -> str:
    """Reject driver names that still carry the responsive code suffix."""
    if not value:
        raise F1ResultsError(f"F1 results table has an empty driver cell: {url}")
    if _DRIVER_CODE_PATTERN.match(value):
        raise F1ResultsError(f"driver name keeps an unseparated code: {value!r}")
    return value


def _source(html: str, url: str, retrieved_at: datetime | None) -> SourceReference:
    """Build the retrieval evidence for one fetched table page."""
    return SourceReference(
        url=url,
        authority="Formula 1",
        retrieved_at=retrieved_at or datetime.now(UTC),
        content_hash=hashlib.sha256(html.encode("utf-8")).hexdigest(),
    )


def parse_race_result(
    html: str,
    url: str,
    *,
    retrieved_at: datetime | None = None,
) -> tuple[list[F1ResultEntry], SourceReference] | None:
    """Parse an official classification table.

    Used for the Grand Prix result and, on sprint weekends, for the sprint
    result page which shares the exact same table shape. Returns None when
    the page has no result table yet (the session has not finished). Raises
    F1ResultsError on any structural surprise.
    """
    extracted = _extract_table(html, RACE_RESULT_HEADER, url)
    if extracted is None:
        return None
    rows, codes = extracted
    entries: list[F1ResultEntry] = []
    for row, code in zip(rows, codes, strict=True):
        position, car_number, driver, team, laps, time_or_status, points = row
        try:
            entry = F1ResultEntry(
                position=position,
                car_number=car_number,
                driver=_driver_name(driver, url),
                code=code,
                team=team,
                laps=int(laps),
                time_or_status=time_or_status,
                points=int(points),
            )
        except (ValueError, TypeError) as error:
            raise F1ResultsError(f"invalid race result row {row!r} at {url}") from error
        entries.append(entry)
    return entries, _source(html, url, retrieved_at)


def parse_starting_grid(
    html: str,
    url: str,
    *,
    retrieved_at: datetime | None = None,
) -> tuple[list[F1GridEntry], SourceReference] | None:
    """Parse the official starting grid table with the same absence rule."""
    extracted = _extract_table(html, STARTING_GRID_HEADER, url)
    if extracted is None:
        return None
    rows, codes = extracted
    entries: list[F1GridEntry] = []
    for row, code in zip(rows, codes, strict=True):
        position, car_number, driver, team, time = row
        try:
            entry = F1GridEntry(
                position=int(position),
                car_number=car_number,
                driver=_driver_name(driver, url),
                code=code,
                team=team,
                time=time,
            )
        except (ValueError, TypeError) as error:
            raise F1ResultsError(f"invalid starting grid row {row!r} at {url}") from error
        entries.append(entry)
    return entries, _source(html, url, retrieved_at)


def parse_qualifying(
    html: str,
    url: str,
    *,
    retrieved_at: datetime | None = None,
) -> tuple[list[F1QualifyingEntry], SourceReference] | None:
    """Parse an official qualifying or sprint-qualifying table.

    Both pages share the Q1/Q2/Q3 column layout. The pole-sitter is the
    entry at position 1; its deciding lap is the deepest non-empty segment.
    """
    extracted = _extract_table(html, QUALIFYING_HEADER, url)
    if extracted is None:
        return None
    rows, codes = extracted
    entries: list[F1QualifyingEntry] = []
    for row, code in zip(rows, codes, strict=True):
        position, car_number, driver, team, q1, q2, q3, laps = row
        try:
            entry = F1QualifyingEntry(
                position=position,
                car_number=car_number,
                driver=_driver_name(driver, url),
                code=code,
                team=team,
                q1=q1,
                q2=q2,
                q3=q3,
                laps=int(laps),
            )
        except (ValueError, TypeError) as error:
            raise F1ResultsError(f"invalid qualifying row {row!r} at {url}") from error
        entries.append(entry)
    return entries, _source(html, url, retrieved_at)


def _validate_event_url(url: str, season: int) -> None:
    """Keep results URLs inside the official results namespace."""
    parsed = urlsplit(url)
    prefix = f"/en/results/{season}/races/"
    inside_namespace = parsed.path.startswith(prefix)
    if parsed.scheme != "https" or parsed.netloc != "www.formula1.com" or not inside_namespace:
        raise F1ResultsError(f"refusing to fetch a foreign results URL: {url}")


class F1ResultsClient:
    """Synchronous client for the official F1 results pages."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        """Inject an HTTP client for tests or create one with bounded timeouts."""
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Release HTTP resources."""
        self._client.close()

    def _get_text(self, url: str, season: int) -> str:
        """Fetch one results page after validating its namespace."""
        _validate_event_url(url, season)
        response = self._client.get(url)
        response.raise_for_status()
        return response.text

    def fetch_round_links(self, season: int) -> list[F1RoundLink]:
        """Return every Grand Prix listed on the season results index."""
        index_url = f"{F1_BASE_URL}/en/results/{season}/races"
        response = self._client.get(index_url)
        response.raise_for_status()
        return discover_results_rounds(response.text, season)

    def fetch_race_result(
        self, link: F1RoundLink
    ) -> tuple[list[F1ResultEntry], SourceReference] | None:
        """Fetch one race classification, or None when it is not published."""
        return parse_race_result(self._get_text(link.result_url, link.season), link.result_url)

    def fetch_starting_grid(
        self, link: F1RoundLink
    ) -> tuple[list[F1GridEntry], SourceReference] | None:
        """Fetch one starting grid, or None when it is not published."""
        return parse_starting_grid(self._get_text(link.grid_url, link.season), link.grid_url)

    def fetch_qualifying(
        self, link: F1RoundLink
    ) -> tuple[list[F1QualifyingEntry], SourceReference] | None:
        """Fetch one qualifying classification, or None when not published."""
        url = link.qualifying_url
        return parse_qualifying(self._get_text(url, link.season), url)

    def fetch_sprint_results(
        self, link: F1RoundLink
    ) -> tuple[list[F1ResultEntry], SourceReference] | None:
        """Fetch one sprint classification, or None when not published."""
        url = link.sprint_results_url
        return parse_race_result(self._get_text(url, link.season), url)

    def fetch_sprint_qualifying(
        self, link: F1RoundLink
    ) -> tuple[list[F1QualifyingEntry], SourceReference] | None:
        """Fetch one sprint qualifying classification, or None when not published."""
        url = link.sprint_qualifying_url
        return parse_qualifying(self._get_text(url, link.season), url)


def results_url_is_official(url: str) -> bool:
    """Expose the namespace rule for tests and cross checks."""
    parsed = urlsplit(urljoin(F1_BASE_URL, url))
    return parsed.netloc == "www.formula1.com" and parsed.scheme == "https"
