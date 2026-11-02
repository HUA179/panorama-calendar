"""VALARM serialization with iOS compatibility fields."""

from panorama_calendar.ics.escape import escape_text
from panorama_calendar.models.event import Alarm


def build_alarm_lines(alarm: Alarm) -> list[str]:
    """Build one VALARM, including independent UID and X-WR-ALARMUID."""
    if not alarm.uid or not alarm.x_wr_alarmuid:
        raise ValueError("alarm identifiers must be initialized by EventRecord")
    if alarm.uid != alarm.x_wr_alarmuid:
        raise ValueError("X-WR-ALARMUID must match the alarm UID")
    return [
        "BEGIN:VALARM",
        f"UID:{alarm.uid}",
        f"X-WR-ALARMUID:{alarm.x_wr_alarmuid}",
        f"ACTION:{alarm.action}",
        f"TRIGGER;RELATED={alarm.related}:{alarm.trigger}",
        f"DESCRIPTION:{escape_text(alarm.description)}",
        "END:VALARM",
    ]
