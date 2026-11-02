"""Jolpica degradation tests."""

import logging

import httpx
import pytest

from panorama_calendar.sources.jolpica import (
    JolpicaClient,
    load_official_schedule_with_optional_cross_check,
)


@pytest.mark.parametrize("status_code", [429, 500])
def test_jolpica_failure_warns_and_preserves_official_schedule(
    status_code: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Rate limits and server errors must not interrupt official generation."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = JolpicaClient(http_client)
    with caplog.at_level(logging.WARNING):
        result = load_official_schedule_with_optional_cross_check(
            2026,
            official_loader=lambda season: [f"official-{season}"],
            jolpica=client,
        )
    client.close()

    assert result == ["official-2026"]
    assert "continuing with the F1 official calendar" in caplog.text


def test_invalid_jolpica_payload_also_degrades(caplog: pytest.LogCaptureFixture) -> None:
    """A successful HTTP response with an invalid schema is non-fatal."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True}, request=request)

    client = JolpicaClient(httpx.Client(transport=httpx.MockTransport(handler)))
    with caplog.at_level(logging.WARNING):
        assert client.fetch_schedule_or_none(2026) is None
    client.close()
    assert "continuing with the F1 official calendar" in caplog.text
