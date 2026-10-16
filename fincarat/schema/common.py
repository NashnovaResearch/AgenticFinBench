"""Shared, frozen types for FinCARAT evaluation artifacts."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitCommit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Probability = Annotated[float, Field(ge=0.0, le=1.0)]
FinancialDateTime = AwareDatetime | date


class FrozenModel(BaseModel):
    """Strict base model used by every persisted FinCARAT schema."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class TimeContext(FrozenModel):
    """The time boundary under which a financial fact is judged."""

    time_basis: NonEmptyStr
    as_of: AwareDatetime
    timezone: NonEmptyStr
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("valid_to")
    @classmethod
    def validity_window_must_be_ordered(
        cls,
        value: AwareDatetime | None,
        info: ValidationInfo,
    ) -> AwareDatetime | None:
        valid_from = info.data.get("valid_from")
        if value is not None and valid_from is not None and value < valid_from:
            raise ValueError("valid_to must not be earlier than valid_from")
        return value


class FileDigest(FrozenModel):
    path: NonEmptyStr
    sha256: Sha256
    size_bytes: int = Field(ge=0)


class RepositoryRevision(FrozenModel):
    repository: NonEmptyStr
    commit: GitCommit
    branch: NonEmptyStr | None = None
    dirty: bool
    diff_sha256: Sha256 | None = None
    subject: str | None = None

    @field_validator("diff_sha256")
    @classmethod
    def dirty_revision_requires_diff_digest(
        cls,
        value: Sha256 | None,
        info: ValidationInfo,
    ) -> Sha256 | None:
        if info.data.get("dirty") and value is None:
            raise ValueError("dirty repository revisions require diff_sha256")
        return value
