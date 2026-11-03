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
    code: str = Field(default="", max_length=3)
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
    code: str = Field(default="", max_length=3)
    team: str = Field(min_length=1)
    time: str = ""


class F1QualifyingEntry(BaseModel):
    """One row of an official qualifying or sprint-qualifying table."""

    model_config = ConfigDict(str_strip_whitespace=True)

    position: str = Field(min_length=1, max_length=4)
    car_number: str = Field(min_length=1, max_length=3)
    driver: str = Field(min_length=1)
    code: str = Field(default="", max_length=3)
    team: str = Field(min_length=1)
    q1: str = ""
    q2: str = ""
    q3: str = ""
    laps: int = Field(ge=0)

    @property
    def best_time(self) -> str:
        """Return the deciding segment time, falling back when Q3 was not run."""
        return self.q3 or self.q2 or self.q1

    def as_pole(self) -> F1GridEntry:
        """View this entry as a pole-position record with its deciding lap."""
        return F1GridEntry(
            position=1,
            car_number=self.car_number,
            driver=self.driver,
            code=self.code,
            team=self.team,
            time=self.best_time,
        )


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
    result_source: SourceReference
    pole: F1GridEntry | None = None
    pole_source: SourceReference | None = None
    sprint_results: list[F1ResultEntry] = Field(default_factory=list)
    sprint_source: SourceReference | None = None
    sprint_pole: F1GridEntry | None = None
    sprint_pole_source: SourceReference | None = None
    fia_classification_url: str | None = None

    @staticmethod
    def _check_classification(entries: list[F1ResultEntry], label: str) -> None:
        """Apply the classification invariants to one results table."""
        car_numbers = [entry.car_number for entry in entries]
        if len(car_numbers) != len(set(car_numbers)):
            raise ValueError(f"{label} results contain duplicate car numbers")
        if not any(entry.position == "1" for entry in entries):
            raise ValueError(f"{label} results are missing the winner")
        numeric_positions = sorted(int(entry.position) for entry in entries if entry.classified)
        if numeric_positions != list(range(1, len(numeric_positions) + 1)):
            raise ValueError(f"{label} classified positions must be a gapless 1..N sequence")

    @model_validator(mode="after")
    def check_consistency(self) -> "F1RaceReport":
        """Reject reports that cannot represent one clean classification."""
        if self.status is ResultStatus.NOT_AVAILABLE:
            raise ValueError("a report requires actual race results")
        self._check_classification(self.results, "race")
        if self.sprint_results:
            self._check_classification(self.sprint_results, "sprint")
        if self.sprint_pole is not None and not self.sprint_results:
            raise ValueError("a sprint pole requires sprint results")
        if self.sprint_results and self.sprint_source is None:
            raise ValueError("sprint results require a retrieval source")
        if self.pole is not None and self.pole_source is None:
            raise ValueError("a pole position requires a retrieval source")
        if self.sprint_pole is not None and self.sprint_pole_source is None:
            raise ValueError("a sprint pole requires a retrieval source")
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
        return self._podium_of(self.results)

    @property
    def sprint_podium(self) -> list[F1ResultEntry]:
        """Return the first three classified sprint finishers in order."""
        return self._podium_of(self.sprint_results)

    @staticmethod
    def _podium_of(entries: list[F1ResultEntry]) -> list[F1ResultEntry]:
        """Return the first three classified finishers of one table."""
        return sorted(
            (entry for entry in entries if entry.classified),
            key=lambda entry: int(entry.position),
        )[:3]

    @property
    def classified_count(self) -> int:
        """Count drivers with a numeric finishing position."""
        return sum(1 for entry in self.results if entry.classified)

    @property
    def dnf_count(self) -> int:
        """Count unclassified drivers (DNF/DNS/NC/DQ)."""
        return len(self.results) - self.classified_count
