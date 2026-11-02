"""Source evidence models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class SourceReference(BaseModel):
    """Reference to evidence supporting an event or a field."""

    model_config = ConfigDict(str_strip_whitespace=True)

    url: str
    authority: str
    retrieved_at: datetime
    content_hash: str | None = None
    evidence_id: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Allow only explicit HTTP(S) source URLs."""
        if not value.startswith(("https://", "http://")):
            raise ValueError("source URL must use HTTP or HTTPS")
        if "\r" in value or "\n" in value:
            raise ValueError("source URL cannot contain line breaks")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: datetime) -> datetime:
        """Require an aware retrieval timestamp."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value
