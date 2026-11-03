"""Reviewed display metadata for F1 events and drivers.

Two small curated registries back the Chinese-facing feeds:

- ``f1_event_names.json`` maps the stable schedule slug to the Chinese Grand
  Prix name and the bilingual host city used in schedule summaries.
- ``f1_drivers.json`` maps the three-letter driver code to the Chinese name
  and the nationality flag emoji used in race reports.

Both files are human-reviewable JSON; loading validates the structure so a
hand edit cannot silently produce a wrong calendar.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")
# Regional indicator symbols U+1F1E6..U+1F1FF, twice, form one flag emoji.
_FLAG_PATTERN = re.compile("^[\U0001f1e6-\U0001f1ff]{2}$")


class F1MetadataError(RuntimeError):
    """Raised when the reviewed F1 display metadata is malformed."""


class F1EventDisplay(BaseModel):
    """Chinese Grand Prix name and bilingual host city for one round."""

    model_config = ConfigDict(str_strip_whitespace=True)

    gp_zh: str = Field(min_length=1)
    city_zh: str = Field(min_length=1)
    city_en: str = Field(min_length=1)


class F1DriverInfo(BaseModel):
    """Chinese name and nationality flag for one driver code."""

    model_config = ConfigDict(str_strip_whitespace=True)

    zh: str = Field(min_length=1)
    flag: str = Field(min_length=1)


def _read_metadata(relative: str) -> dict[str, object]:
    """Read one packaged metadata JSON file with a readable failure."""
    resource = files("panorama_calendar").joinpath("data", relative)
    if not resource.is_file():
        raise F1MetadataError(f"F1 metadata not found: data/{relative}")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise F1MetadataError(f"F1 metadata is not a non-empty JSON object: data/{relative}")
    return payload


@lru_cache(maxsize=1)
def load_f1_event_names() -> dict[str, F1EventDisplay]:
    """Load the reviewed slug-to-display registry for schedule titles."""
    payload = _read_metadata("f1_event_names.json")
    registry: dict[str, F1EventDisplay] = {}
    for slug, raw in payload.items():
        if not _SLUG_PATTERN.fullmatch(slug):
            raise F1MetadataError(f"invalid F1 event slug in metadata: {slug!r}")
        try:
            registry[slug] = F1EventDisplay.model_validate(raw)
        except ValueError as error:
            raise F1MetadataError(f"invalid F1 event display for {slug!r}: {error}") from error
    return registry


@lru_cache(maxsize=1)
def load_f1_driver_registry() -> dict[str, F1DriverInfo]:
    """Load the reviewed driver-code registry for race report lines."""
    payload = _read_metadata("f1_drivers.json")
    registry: dict[str, F1DriverInfo] = {}
    for code, raw in payload.items():
        if not _CODE_PATTERN.fullmatch(code):
            raise F1MetadataError(f"invalid F1 driver code in metadata: {code!r}")
        try:
            info = F1DriverInfo.model_validate(raw)
        except ValueError as error:
            raise F1MetadataError(f"invalid F1 driver info for {code!r}: {error}") from error
        if not _FLAG_PATTERN.fullmatch(info.flag):
            raise F1MetadataError(f"driver {code!r} has a non-flag emoji: {info.flag!r}")
        registry[code] = info
    return registry
