"""F1 domain models with stable event identity and explicit time evidence."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from panorama_calendar.models.enums import EventStatus, ResultStatus, SessionKind
from panorama_calendar.models.source import SourceReference


class F1Session(BaseModel):
    """One authoritative F1 session in a season and Grand Prix."""

    model_config = ConfigDict(str_strip_whitespace=True)

    season: int = Field(ge=1950, le=2100)
    event_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    grand_prix_name: str = Field(min_length=1)
    session_kind: SessionKind
    start_at_utc: datetime
    end_at_utc: datetime | None = None
    circuit_timezone: str
    location: str = ""
    status: EventStatus = EventStatus.CONFIRMED
    source: SourceReference

    @field_validator("start_at_utc", "end_at_utc")
    @classmethod
    def require_aware_datetimes(cls, value: datetime | None) -> datetime | None:
        """Reject source timestamps without an explicit UTC offset."""
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("F1 session timestamps must be timezone-aware")
        return value

    @field_validator("circuit_timezone")
    @classmethod
    def require_iana_timezone(cls, value: str) -> str:
        """Accept only an installed IANA timezone name."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA timezone: {value}") from error
        return value

    @model_validator(mode="after")
    def normalize_and_validate(self) -> "F1Session":
        """Normalize timed fields to UTC and enforce chronological ordering."""
        self.start_at_utc = self.start_at_utc.astimezone(UTC)
        if self.start_at_utc.year != self.season:
            raise ValueError("F1 session start must belong to the requested season")
        if self.end_at_utc is not None:
            self.end_at_utc = self.end_at_utc.astimezone(UTC)
            if self.end_at_utc <= self.start_at_utc:
                raise ValueError("F1 session end must be after its start")
        return self

    @property
    def event_key(self) -> str:
        """Return an identity independent of sponsor titles and start times."""
        return f"f1:session:{self.season}:{self.event_id}:{self.session_kind.value}"


class F1ResultEntry(BaseModel):
    """One row of the official race classification table."""

    model_config = ConfigDict(str_strip_whitespace=True)

    position: str = Field(min_length=1, max_length=4)
    car_number: str = Field(min_length=1, max_length=3)
    driver: str = Field(min_length=1)
    team: str = Field(min_length=1)
    laps: int = Field(ge=0)
    time_or_status: str = Field(min_length=1)
    points: int = Field(ge=0)

    @property
    def classified(self) -> bool:
        """True when the driver holds a numeric finishing position."""
        return self.position.isdigit()


class F1GridEntry(BaseModel):
    """One row of the official starting grid table."""

    model_config = ConfigDict(str_strip_whitespace=True)

    position: int = Field(ge=1)
    car_number: str = Field(min_length=1, max_length=3)
    driver: str = Field(min_length=1)
    team: str = Field(min_length=1)
    time: str = ""


class F1RaceReport(BaseModel):
    """Normalised race-day facts for one Grand Prix with FIA status evidence."""

    model_config = ConfigDict(str_strip_whitespace=True)

    season: int = Field(ge=1950, le=2100)
    event_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    grand_prix_name: str = Field(min_length=1)
    official_name: str | None = None
    race_date: date
    status: ResultStatus = ResultStatus.PROVISIONAL
    results: list[F1ResultEntry] = Field(min_length=1)
    grid: list[F1GridEntry] = Field(default_factory=list)
    result_source: SourceReference
    grid_source: SourceReference | None = None
    fia_classification_url: str | None = None

    @model_validator(mode="after")
    def check_consistency(self) -> "F1RaceReport":
        """Reject reports that cannot represent one clean classification."""
        if self.status is ResultStatus.NOT_AVAILABLE:
            raise ValueError("a report requires actual race results")
        car_numbers = [entry.car_number for entry in self.results]
        if len(car_numbers) != len(set(car_numbers)):
            raise ValueError("race results contain duplicate car numbers")
        if not any(entry.position == "1" for entry in self.results):
            raise ValueError("race results are missing the winner")
        numeric_positions = sorted(
            int(entry.position) for entry in self.results if entry.classified
        )
        if numeric_positions != list(range(1, len(numeric_positions) + 1)):
            raise ValueError("classified positions must be a gapless 1..N sequence")
        if self.grid:
            positions = [entry.position for entry in self.grid]
            if sorted(positions) != list(range(1, len(positions) + 1)):
                raise ValueError("starting grid positions must be a gapless 1..N sequence")
        if self.fia_classification_url is not None and not self.fia_classification_url.startswith(
            "https://"
        ):
            raise ValueError("FIA classification link must be HTTPS")
        return self

    @property
    def event_key(self) -> str:
        """Keep report identity separate from schedule session identity."""
        return f"report:{self.season}:{self.event_id}"

    @property
    def podium(self) -> list[F1ResultEntry]:
        """Return the first three classified finishers in order."""
        return sorted(
            (entry for entry in self.results if entry.classified),
            key=lambda entry: int(entry.position),
        )[:3]

    @property
    def pole(self) -> F1GridEntry | None:
        """Return the pole-sitter when the starting grid is available."""
        return self.grid[0] if self.grid else None

    @property
    def classified_count(self) -> int:
        """Count drivers with a numeric finishing position."""
        return sum(1 for entry in self.results if entry.classified)

    @property
    def dnf_count(self) -> int:
        """Count unclassified drivers (DNF/DNS/NC)."""
        return len(self.results) - self.classified_count
