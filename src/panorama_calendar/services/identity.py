"""Deterministic identifiers for events and alarms."""

import hashlib

DEFAULT_UID_DOMAIN = "panorama.local"


def _validate_identifier_part(value: str, name: str) -> None:
    """Reject values that could break identifier serialization."""
    if not value or "\r" in value or "\n" in value:
        raise ValueError(f"{name} must be non-empty and single-line")


def make_uid(event_key: str, domain: str = DEFAULT_UID_DOMAIN) -> str:
    """Create a stable UID from the real-world event key, not its title or date."""
    _validate_identifier_part(event_key, "event_key")
    _validate_identifier_part(domain, "domain")
    digest = hashlib.sha256(event_key.encode("utf-8")).hexdigest()[:32]
    return f"event-{digest}@{domain}"


def make_alarm_uid(
    event_key: str,
    alarm_key: str,
    domain: str = DEFAULT_UID_DOMAIN,
) -> str:
    """Create an independent, stable UID for one VALARM component."""
    _validate_identifier_part(alarm_key, "alarm_key")
    _validate_identifier_part(domain, "domain")
    digest = hashlib.sha256(f"{event_key}\0{alarm_key}".encode()).hexdigest()[:32]
    return f"alarm-{digest}@{domain}"
