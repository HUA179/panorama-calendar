"""Loaders and integrity checks for the curated official datasets.

Every dataset under ``panorama_calendar/data`` is a human-reviewable JSON file
that keeps the official wording verbatim. Loading performs structural checks so
that a hand-edited file cannot silently produce a wrong calendar.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from importlib.resources import files
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from panorama_calendar.models.enums import CalendarKind

HOLIDAY_DIRECTORIES: dict[CalendarKind, str] = {
    CalendarKind.CN_HOLIDAY: "cn_holidays",
    CalendarKind.GX_HOLIDAY: "gx_holidays",
}


class DatasetError(RuntimeError):
    """Raised when a dataset is missing or internally inconsistent."""


class NoticeHeader(BaseModel):
    """Provenance of the official notice a dataset was transcribed from."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    doc_number: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    published_at: date
    url: str = Field(min_length=1)
    retrieved_at: datetime


class HolidayPeriod(BaseModel):
    """One continuous rest period as stated by the official notice."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    start: date
    end: date
    days: int = Field(ge=1, le=31)
    raw: str = Field(min_length=1)
    note: str = ""

    @model_validator(mode="after")
    def validate_span(self) -> HolidayPeriod:
        """The declared day count must match the actual span."""
        actual = (self.end - self.start).days + 1
        if actual != self.days:
            raise ValueError(
                f"{self.name}: declared {self.days} days but span "
                f"{self.start}..{self.end} covers {actual} days"
            )
        return self


class AdjustmentWorkday(BaseModel):
    """A weekend day that becomes a working day because of holiday adjustment."""

    model_config = ConfigDict(str_strip_whitespace=True)

    date: date
    reason: str = Field(min_length=1)
    raw: str = Field(min_length=1)


class HolidayDataset(BaseModel):
    """A full year of rest periods and adjustment workdays for one calendar."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_version: int = Field(ge=1)
    year: int = Field(ge=1949, le=2100)
    calendar_kind: CalendarKind
    notice: NoticeHeader
    periods: list[HolidayPeriod] = Field(default_factory=list)
    workdays: list[AdjustmentWorkday] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_consistency(self) -> HolidayDataset:
        """Reject overlapping periods and workdays that fall inside a rest day."""
        names = [period.name for period in self.periods]
        if len(names) != len(set(names)):
            raise ValueError("duplicate period names in dataset")

        ordered = sorted(self.periods, key=lambda period: period.start)
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if later.start <= earlier.end:
                raise ValueError(f"periods overlap: {earlier.name} and {later.name}")

        for period in self.periods:
            if period.end.year != self.year or period.start.year != self.year:
                raise ValueError(f"{period.name} spans outside {self.year}")

        for workday in self.workdays:
            if workday.date.year != self.year:
                raise ValueError(f"adjustment workday {workday.date} is outside {self.year}")
            for period in self.periods:
                if period.start <= workday.date <= period.end:
                    raise ValueError(
                        f"{workday.date} is marked as a workday but falls inside {period.name}"
                    )
        return self

    @property
    def evidence_hash(self) -> str:
        """Stable hash over the verbatim official clauses of this dataset."""
        joined = "\n".join(item.raw for item in [*self.periods, *self.workdays])
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def rest_dates(self) -> set[date]:
        """Expand every rest period into individual dates."""
        dates: set[date] = set()
        for period in self.periods:
            cursor = period.start
            while cursor <= period.end:
                dates.add(cursor)
                cursor += timedelta(days=1)
        return dates


class FixedRule(BaseModel):
    """A memorial day that falls on the same month and day every year."""

    type: Literal["fixed"] = "fixed"
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)


class NthWeekdayRule(BaseModel):
    """A memorial day defined as the nth weekday of a month."""

    type: Literal["nth_weekday"] = "nth_weekday"
    month: int = Field(ge=1, le=12)
    weekday: int = Field(ge=0, le=6, description="Monday=0, Sunday=6")
    nth: int = Field(ge=1, le=5)


DateRule = Annotated[FixedRule | NthWeekdayRule, Field(discriminator="type")]


class AnniversaryEntry(BaseModel):
    """One nationally established memorial day."""

    model_config = ConfigDict(str_strip_whitespace=True)

    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    rule: DateRule
    since: int = Field(ge=1949, le=2100)
    until: int | None = Field(default=None, ge=1949, le=2100)
    legal_basis: str = Field(min_length=1)

    def resolve(self, year: int) -> date | None:
        """Return this entry's date in ``year``, or None before establishment."""
        if year < self.since or (self.until is not None and year > self.until):
            return None
        if isinstance(self.rule, FixedRule):
            try:
                return date(year, self.rule.month, self.rule.day)
            except ValueError:
                return None
        first = date(year, self.rule.month, 1)
        offset = (self.rule.weekday - first.weekday()) % 7
        candidate = first + timedelta(days=offset + 7 * (self.rule.nth - 1))
        if candidate.month != self.rule.month:
            return None
        return candidate


class AnniversaryRegistry(BaseModel):
    """The whole memorial-day register."""

    schema_version: int = Field(ge=1)
    description: str = ""
    entries: list[AnniversaryEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_keys(self) -> AnniversaryRegistry:
        """Guarantee stable identity across releases."""
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate anniversary keys")
        return self

    def resolve_year(self, year: int) -> list[tuple[AnniversaryEntry, date]]:
        """Return every entry that has a date in ``year``, sorted by date."""
        resolved = [
            (entry, moment)
            for entry in self.entries
            if (moment := entry.resolve(year)) is not None
        ]
        return sorted(resolved, key=lambda pair: (pair[1], pair[0].key))


def _read_json(relative: str) -> dict[str, object]:
    """Read one packaged JSON file with a readable failure message."""
    resource = files("panorama_calendar").joinpath("data", *relative.split("/"))
    if not resource.is_file():
        raise DatasetError(f"dataset not found: data/{relative}")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DatasetError(f"dataset is not a JSON object: data/{relative}")
    return payload


def available_holiday_years(calendar_kind: CalendarKind) -> list[int]:
    """List the years that have a transcribed dataset for this calendar."""
    directory = HOLIDAY_DIRECTORIES.get(calendar_kind)
    if directory is None:
        return []
    folder = files("panorama_calendar").joinpath("data", directory)
    return sorted(
        int(item.name.removesuffix(".json"))
        for item in folder.iterdir()
        if item.name.endswith(".json")
    )


def load_holiday_dataset(calendar_kind: CalendarKind, year: int) -> HolidayDataset:
    """Load and validate one year of a holiday calendar.

    Args:
        calendar_kind: Which subscription the dataset belongs to.
        year: Calendar year of the notice.

    Returns:
        The validated dataset.

    Raises:
        DatasetError: If the calendar has no datasets, the year is missing, or
            the file is structurally invalid.
    """
    if calendar_kind not in HOLIDAY_DIRECTORIES:
        raise DatasetError(f"{calendar_kind} has no transcribed holiday datasets")
    directory = HOLIDAY_DIRECTORIES[calendar_kind]
    years = available_holiday_years(calendar_kind)
    if year not in years:
        raise DatasetError(
            f"no {calendar_kind} dataset for {year}; available: {years or 'none'}"
        )
    try:
        dataset = HolidayDataset.model_validate(_read_json(f"{directory}/{year}.json"))
    except ValueError as error:
        raise DatasetError(f"invalid {calendar_kind} dataset for {year}: {error}") from error
    if dataset.calendar_kind is not calendar_kind:
        raise DatasetError(
            f"dataset {year}.json declares {dataset.calendar_kind}, expected {calendar_kind}"
        )
    return dataset


def load_anniversary_registry() -> AnniversaryRegistry:
    """Load the packaged memorial-day register."""
    try:
        return AnniversaryRegistry.model_validate(_read_json("anniversaries.json"))
    except ValueError as error:
        raise DatasetError(f"invalid anniversary registry: {error}") from error
