"""Shared enumerations for the calendar domain."""

from enum import StrEnum


class CalendarKind(StrEnum):
    """Supported independent calendar feeds."""

    CN_HOLIDAY = "CN_HOLIDAY"
    GX_HOLIDAY = "GX_HOLIDAY"
    MEMORIAL = "MEMORIAL"
    F1_SCHEDULE = "F1_SCHEDULE"
    F1_REPORT = "F1_REPORT"


class EventKind(StrEnum):
    """Business meaning of an event."""

    REST_PERIOD = "REST_PERIOD"
    ADJUSTED_WORKDAY = "ADJUSTED_WORKDAY"
    MEMORIAL_DAY = "MEMORIAL_DAY"
    F1_SESSION = "F1_SESSION"
    F1_REPORT = "F1_REPORT"


class SessionKind(StrEnum):
    """F1 sessions included in the product."""

    QUALIFYING = "QUALIFYING"
    SPRINT_QUALIFYING = "SPRINT_QUALIFYING"
    SPRINT = "SPRINT"
    RACE = "RACE"


class EventStatus(StrEnum):
    """Lifecycle state of a calendar event."""

    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class ResultStatus(StrEnum):
    """Lifecycle state of sporting results."""

    NOT_AVAILABLE = "NOT_AVAILABLE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    AMENDED = "AMENDED"
