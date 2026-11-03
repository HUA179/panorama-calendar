"""ICS generation and iOS alarm compatibility tests."""

import pytest

from panorama_calendar.ics import render_calendar, validate_ics_bytes
from panorama_calendar.ics.folding import CRLF
from panorama_calendar.models import EventRecord


def _unfold(data: bytes) -> str:
    """Unfold a complete test document for semantic assertions."""
    return data.replace(CRLF + b" ", b"").replace(CRLF + b"\t", b"").decode("utf-8")


def test_generate_event_with_valarm_and_x_wr_alarmuid(workday_event: EventRecord) -> None:
    """Emit an independent UID and matching X-WR-ALARMUID inside VALARM."""
    data = render_calendar([workday_event], "全国假期｜提醒验证")
    validate_ics_bytes(data)
    text = _unfold(data)
    alarm_block = text.split("BEGIN:VALARM", maxsplit=1)[1].split("END:VALARM", maxsplit=1)[0]
    alarm = workday_event.alarms[0]

    assert alarm.uid is not None
    assert alarm.uid != workday_event.uid
    assert f"UID:{alarm.uid}\n" in alarm_block.replace("\r\n", "\n")
    assert f"X-WR-ALARMUID:{alarm.uid}\n" in alarm_block.replace("\r\n", "\n")
    assert "TRIGGER;RELATED=START:-PT4H" in alarm_block
    assert "ACTION:DISPLAY" in alarm_block


def test_every_physical_line_is_at_most_75_octets(workday_event: EventRecord) -> None:
    """Long Chinese content is folded by bytes, not character count."""
    data = render_calendar([workday_event], "全国假期｜提醒验证")
    assert all(len(line) <= 75 for line in data[:-2].split(CRLF))
    assert data.endswith(CRLF)


def test_calendar_advertises_refresh_interval(workday_event: EventRecord) -> None:
    """Clients are told how often to re-poll instead of guessing."""
    text = _unfold(render_calendar([workday_event], "全国假期｜提醒验证"))
    assert "X-PUBLISHED-TTL:PT6H" in text
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT6H" in text
    header = text.split("BEGIN:VEVENT", maxsplit=1)[0]
    assert header.count("X-PUBLISHED-TTL") == 1
    assert header.count("REFRESH-INTERVAL") == 1


def test_refresh_interval_is_configurable(workday_event: EventRecord) -> None:
    """The interval is a parameter, so the cloud cadence can change alone."""
    text = _unfold(render_calendar([workday_event], "全国假期｜提醒验证", refresh_interval="PT1H"))
    assert "X-PUBLISHED-TTL:PT1H" in text
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT1H" in text


def test_multi_line_refresh_interval_is_rejected(workday_event: EventRecord) -> None:
    """A header-injection attempt must fail loudly, not corrupt the feed."""
    with pytest.raises(ValueError, match="single-line"):
        render_calendar([workday_event], "全国假期｜提醒验证", refresh_interval="PT6H\r\nX-EVIL:1")
