"""Read the revision chain that subscribers have already received.

The published ``.ics`` is the only artefact that witnesses what clients actually
hold; the local snapshot is a cache that can be lost, restored from an old
backup or simply never written on a fresh runner. Parsing the live feed gives the
sequence floor that keeps ``SEQUENCE`` monotonic when that happens.
"""

from __future__ import annotations

from pathlib import Path

from icalendar import Calendar


class FeedSnapshotError(RuntimeError):
    """Raised when a published feed exists but cannot be trusted."""


def read_published_sequences(path: Path) -> dict[str, int]:
    """Return ``UID`` to highest published ``SEQUENCE`` for one feed.

    Args:
        path: The calendar file currently published for this feed.

    Returns:
        An empty mapping when the file does not exist yet, otherwise one entry
        per event UID. Duplicate UIDs keep the highest sequence.

    Raises:
        FeedSnapshotError: The file exists but is unreadable, unparsable, or
            contains an event without a usable UID or sequence. Guessing here
            would silently publish a lower version, so the build stops instead.
    """
    if not path.is_file():
        return {}
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise FeedSnapshotError(f"cannot read published feed {path}: {error}") from error
    try:
        calendar = Calendar.from_ical(raw)
    except Exception as error:  # noqa: BLE001 - third-party parser raises many types
        raise FeedSnapshotError(f"published feed {path} is not valid iCalendar: {error}") from error

    sequences: dict[str, int] = {}
    for component in calendar.walk("VEVENT"):
        uid = component.get("UID")
        if uid is None:
            raise FeedSnapshotError(f"published feed {path} has an event without UID")
        raw_sequence = component.get("SEQUENCE", 0)
        try:
            sequence = int(raw_sequence)
        except (TypeError, ValueError) as error:
            raise FeedSnapshotError(
                f"published feed {path} has a non-numeric SEQUENCE for {uid}"
            ) from error
        if sequence < 0:
            raise FeedSnapshotError(f"published feed {path} has a negative SEQUENCE for {uid}")
        key = str(uid)
        sequences[key] = max(sequences.get(key, -1), sequence)
    return sequences
