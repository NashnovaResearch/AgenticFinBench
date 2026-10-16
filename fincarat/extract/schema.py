"""Claim extraction contracts, separate from truth and legacy weak labels."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from fincarat.schema import AtomicClaim, ClaimSlate, FrozenModel
from fincarat.schema.common import Identifier, NonEmptyStr, Sha256

CLAIM_EXTRACTION_SCHEMA_VERSION = "fincarat-claim-extraction-v1"


class ExtractionMode(StrEnum):
    EXTRACT = "extract"
    REVIEW = "review"


class ExtractionStatus(StrEnum):
    COMPLETE = "complete"
    INVALID = "invalid"


class ExtractionRunStatus(StrEnum):
    COMPLETE = "complete"
    PRIMARY_FAILED = "primary_failed"
    REVIEW_FAILED = "review_failed"


class AnswerUnitAnchor(FrozenModel):
    unit_id: Identifier
    text: NonEmptyStr
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def span_must_be_ordered(self) -> AnswerUnitAnchor:
        if self.end <= self.start:
            raise ValueError("answer unit end must be greater than start")
        return self


class ClaimExtractionRequest(FrozenModel):
    schema_version: Literal[CLAIM_EXTRACTION_SCHEMA_VERSION] = CLAIM_EXTRACTION_SCHEMA_VERSION
    mode: ExtractionMode
    query_id: Identifier
    query: NonEmptyStr
    answer: NonEmptyStr
    answer_sha256: Sha256
    as_of: AwareDatetime | None = None
    answer_units: tuple[AnswerUnitAnchor, ...]
    candidate_claims: tuple[AtomicClaim, ...] = ()

    @model_validator(mode="after")
    def review_requires_candidates(self) -> ClaimExtractionRequest:
        if self.mode == ExtractionMode.REVIEW and not self.candidate_claims:
            raise ValueError("review mode requires candidate_claims")
        if self.mode == ExtractionMode.EXTRACT and self.candidate_claims:
            raise ValueError("extract mode cannot include candidate_claims")
        return self


class ExtractionError(FrozenModel):
    line_number: int = Field(ge=1)
    code: Identifier
    detail: NonEmptyStr


class ClaimExtractionBatch(FrozenModel):
    schema_version: Literal[CLAIM_EXTRACTION_SCHEMA_VERSION] = CLAIM_EXTRACTION_SCHEMA_VERSION
    query_id: Identifier
    model: NonEmptyStr
    status: ExtractionStatus
    claims: tuple[AtomicClaim, ...]
    errors: tuple[ExtractionError, ...]
    normalizations: tuple[ExtractionError, ...] = ()
    raw_response_sha256: Sha256
    raw_response: str | None = None

    @model_validator(mode="after")
    def status_matches_claims(self) -> ClaimExtractionBatch:
        if self.status == ExtractionStatus.COMPLETE and (not self.claims or self.errors):
            raise ValueError("complete extraction requires claims and no errors")
        if self.status == ExtractionStatus.INVALID and self.claims:
            raise ValueError("invalid extraction cannot contain accepted claims")
        return self


class ClaimExtractionRun(FrozenModel):
    query_id: Identifier
    status: ExtractionRunStatus
    primary: ClaimExtractionBatch
    primary_attempts: tuple[ClaimExtractionBatch, ...] = ()
    review: ClaimExtractionBatch | None = None
    review_attempts: tuple[ClaimExtractionBatch, ...] = ()
    claim_slate: ClaimSlate | None = None

    @model_validator(mode="after")
    def completed_run_requires_slate(self) -> ClaimExtractionRun:
        if self.status == ExtractionRunStatus.COMPLETE:
            if self.claim_slate is None:
                raise ValueError("complete extraction run requires claim_slate")
        elif self.claim_slate is not None:
            raise ValueError("failed extraction run cannot contain a claim_slate")
        return self
