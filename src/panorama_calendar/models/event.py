"""Unified event and alarm models."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from panorama_calendar.models.enums import CalendarKind, EventKind, EventStatus, ResultStatus
from panorama_calendar.models.source import SourceReference
from panorama_calendar.services.identity import DEFAULT_UID_DOMAIN, make_alarm_uid, make_uid


class Alarm(BaseModel):
    """Display alarm with iOS compatibility identifiers."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str = "DISPLAY"
    trigger: str = "-PT4H"
    related: str = "START"
    description: str
    purpose: str = "reminder"
    uid: str | None = None
    x_wr_alarmuid: str | None = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        """Only DISPLAY is supported by this project."""
        if value != "DISPLAY":
            raise ValueError("only DISPLAY alarms are supported")
        return value

    @field_validator("related")
    @classmethod
    def validate_related(cls, value: str) -> str:
        """Only start-relative alarms are currently emitted."""
        if value != "START":
            raise ValueError("only START-relative alarms are supported")
        return value

    @field_validator("trigger")
    @classmethod
    def validate_trigger(cls, value: str) -> str:
        """Accept a constrained duration instead of arbitrary ICS text."""
        import re

        if not re.fullmatch(r"-?P(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+S)?)?", value):
            raise ValueError("trigger must be an ISO 8601 duration")
        if value in {"P", "-P", "PT", "-PT"}:
            raise ValueError("trigger duration cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_extension_uid(self) -> "Alarm":
        """Keep the iOS extension equal to the independent alarm UID."""
        if self.uid is not None and self.x_wr_alarmuid is None:
            self.x_wr_alarmuid = self.uid
        if self.uid is not None and self.x_wr_alarmuid != self.uid:
            raise ValueError("x_wr_alarmuid must match the alarm UID")
        return self


class EventRecord(BaseModel):
    """Calendar-independent representation of an all-day or timed event."""

    model_config = ConfigDict(str_strip_whitespace=True)

    event_key: str = Field(min_length=1)
    uid: str | None = None
    calendar_kind: CalendarKind
    event_kind: EventKind
    summary: str = Field(min_length=1)
    description: str = ""
    location: str = ""
    start_date: date | None = None
    end_date_exclusive: date | None = None
    start_at_utc: datetime | None = None
    end_at_utc: datetime | None = None
    source_timezone: str | None = None
    status: EventStatus = EventStatus.CONFIRMED
    result_status: ResultStatus = ResultStatus.NOT_AVAILABLE
    sequence: int = Field(default=0, ge=0)
    dtstamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_modified: datetime | None = None
    sources: list[SourceReference] = Field(default_factory=list)
    alarms: list[Alarm] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    transparent: bool = True
    end_estimated: bool = False

    @field_validator("dtstamp", "last_modified", "start_at_utc", "end_at_utc")
    @classmethod
    def require_aware_datetimes(cls, value: datetime | None) -> datetime | None:
        """Reject naive datetimes at the model boundary."""
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_temporal_model(self) -> "EventRecord":
        """Enforce exactly one time model and stable event/alarm identifiers."""
        if self.start_date is not None:
            if self.end_date_exclusive is None:
                raise ValueError("all-day events require end_date_exclusive")
            if self.start_at_utc is not None or self.end_at_utc is not None:
                raise ValueError("all-day events cannot also use timed fields")
            if self.end_date_exclusive <= self.start_date:
                raise ValueError("end_date_exclusive must be after start_date")
        else:
            if self.start_at_utc is None:
                raise ValueError("timed events require start_at_utc")
            if self.end_date_exclusive is not None:
                raise ValueError("timed events cannot use end_date_exclusive")
            self.start_at_utc = self.start_at_utc.astimezone(UTC)
            if self.end_at_utc is not None:
                self.end_at_utc = self.end_at_utc.astimezone(UTC)
                if self.end_at_utc <= self.start_at_utc:
                    raise ValueError("end_at_utc must be after start_at_utc")

        self.dtstamp = self.dtstamp.astimezone(UTC)
        if self.last_modified is not None:
            self.last_modified = self.last_modified.astimezone(UTC)
        if self.source_timezone:
            try:
                ZoneInfo(self.source_timezone)
            except ZoneInfoNotFoundError as error:
                raise ValueError(f"unknown IANA timezone: {self.source_timezone}") from error

        if self.uid is None:
            self.uid = make_uid(self.event_key)
        domain = self.uid.rsplit("@", maxsplit=1)[-1] if "@" in self.uid else DEFAULT_UID_DOMAIN
        seen_alarm_uids: set[str] = set()
        for index, alarm in enumerate(self.alarms):
            if alarm.uid is None:
                alarm.uid = make_alarm_uid(self.event_key, f"{index}:{alarm.purpose}", domain)
                alarm.x_wr_alarmuid = alarm.uid
            if alarm.uid == self.uid or alarm.uid in seen_alarm_uids:
                raise ValueError("alarm UIDs must be independent and unique")
            seen_alarm_uids.add(alarm.uid)
        return self
