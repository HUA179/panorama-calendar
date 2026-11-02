"""Reading the revision floor from the feed that is already published."""

from pathlib import Path

import pytest

from panorama_calendar.ics import render_calendar
from panorama_calendar.models import EventRecord
from panorama_calendar.services.feed_snapshot import FeedSnapshotError, read_published_sequences


def test_missing_feed_means_first_build(tmp_path: Path) -> None:
    """Nothing published yet is a normal state, not an error."""
    assert read_published_sequences(tmp_path / "absent.ics") == {}


def test_sequences_are_read_per_uid(tmp_path: Path, workday_event: EventRecord) -> None:
    """The published SEQUENCE becomes the floor for the next build."""
    published = workday_event.model_copy(deep=True)
    published.sequence = 6
    path = tmp_path / "feed.ics"
    path.write_bytes(render_calendar([published], "测试日历"))

    sequences = read_published_sequences(path)

    assert sequences == {published.uid: 6}


def test_duplicate_uid_keeps_the_highest_sequence(
    tmp_path: Path,
    workday_event: EventRecord,
) -> None:
    """A feed with repeated UIDs still yields a safe floor."""
    older = workday_event.model_copy(deep=True)
    older.sequence = 2
    newer = workday_event.model_copy(deep=True)
    newer.sequence = 5
    path = tmp_path / "feed.ics"
    path.write_bytes(render_calendar([older, newer], "测试日历"))

    assert read_published_sequences(path) == {older.uid: 5}


def test_unparsable_feed_stops_the_build(tmp_path: Path) -> None:
    """Guessing a floor would publish a lower version, so this fails closed."""
    path = tmp_path / "broken.ics"
    path.write_bytes(b"BEGIN:VCALENDAR\r\nnot a property line\r\n")

    with pytest.raises(FeedSnapshotError, match="not valid iCalendar"):
        read_published_sequences(path)


def test_event_without_uid_is_rejected(tmp_path: Path) -> None:
    """A published event without UID cannot be matched to a revision chain."""
    path = tmp_path / "empty-uid.ics"
    path.write_bytes(
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        b"DTSTAMP:20260101T000000Z\r\nSEQUENCE:3\r\n"
        b"SUMMARY:x\r\nDTSTART;VALUE=DATE:20260101\r\n"
        b"END:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    with pytest.raises(FeedSnapshotError, match="without UID"):
        read_published_sequences(path)
