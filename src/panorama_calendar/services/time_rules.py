"""Strict timezone conversions for F1 schedule and report events."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def local_datetime_to_utc_strict(value: datetime, timezone: str) -> datetime:
    """Convert a naive local datetime only when it has one unambiguous instant.

    Args:
        value: Naive local wall-clock datetime.
        timezone: IANA timezone name governing the local value.

    Returns:
        The corresponding aware UTC datetime.

    Raises:
        ValueError: If the input is aware or the local time is invalid/ambiguous.
    """
    if value.tzinfo is not None or value.utcoffset() is not None:
        raise ValueError("local source datetime must be naive")
    zone = ZoneInfo(timezone)
    candidates: list[datetime] = []
    for fold in (0, 1):
        local = value.replace(tzinfo=zone, fold=fold)
        converted = local.astimezone(UTC)
        roundtrip = converted.astimezone(zone)
        if roundtrip.replace(tzinfo=None) == value and converted not in candidates:
            candidates.append(converted)
    if len(candidates) != 1:
        raise ValueError(f"local time {value.isoformat()} is invalid or ambiguous in {timezone}")
    return candidates[0]
