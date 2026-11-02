"""Optional Jolpica cross-checks that never block official F1 data."""

import logging
from collections.abc import Callable, Sequence

import httpx

logger = logging.getLogger(__name__)


class JolpicaClient:
    """Small synchronous client for optional Jolpica schedule data."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 10.0) -> None:
        """Inject a transport for tests or create a bounded HTTP client."""
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Release HTTP resources."""
        self._client.close()

    def fetch_schedule_or_none(self, season: int) -> dict[str, object] | None:
        """Return schedule JSON, or log WARNING and return None on any failure."""
        url = f"https://api.jolpi.ca/ergast/f1/{season}.json"
        try:
            response = self._client.get(url)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or "MRData" not in payload:
                raise ValueError("Jolpica response is missing MRData")
            return payload
        except (httpx.HTTPError, ValueError) as error:
            logger.warning(
                "Jolpica request failed; continuing with the F1 official calendar: %s",
                error,
            )
            return None


def load_official_schedule_with_optional_cross_check[T](
    season: int,
    official_loader: Callable[[int], Sequence[T]],
    jolpica: JolpicaClient,
) -> list[T]:
    """Load authoritative F1 data and make Jolpica strictly optional.

    Official-source errors intentionally propagate. Jolpica errors are handled
    by fetch_schedule_or_none and cannot interrupt generation.
    """
    official_events = list(official_loader(season))
    jolpica.fetch_schedule_or_none(season)
    return official_events
