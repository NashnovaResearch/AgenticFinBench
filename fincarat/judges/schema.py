"""Strict semantic-judge request and response contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from fincarat.schema import (
    AtomicClaim,
    EvidenceAxis,
    EvidenceCompleteness,
    FrozenModel,
    ModelErrorKind,
    TruthAxis,
    TruthFact,
    VerdictLabel,
)
from fincarat.schema.common import Identifier, NonEmptyStr, Probability, Sha256

SEMANTIC_JUDGE_SCHEMA_VERSION = "fincarat-semantic-judge-v1"


class JudgeRole(StrEnum):
    PRIMARY = "primary"
    STRONG_REVIEW = "strong_review"
    HETEROGENEOUS_REVIEW = "heterogeneous_review"


class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    NONE = "none"


class BatchStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INVALID = "invalid"


_LABEL_BY_AXES = {
    (EvidenceAxis.SUPPORTED, TruthAxis.CORRECT): VerdictLabel.SUPPORTED,
    (EvidenceAxis.NOT_SUPPORTED, TruthAxis.CORRECT): VerdictLabel.UNSUPPORTED_BUT_TRUE,
    (EvidenceAxis.SUPPORTED, TruthAxis.INCORRECT): VerdictLabel.SOURCE_ERROR,
    (EvidenceAxis.NOT_SUPPORTED, TruthAxis.INCORRECT): VerdictLabel.MODEL_ERROR,
}


class EvidenceExcerpt(FrozenModel):
    evidence_id: Identifier
    source_type: NonEmptyStr
    text: NonEmptyStr
    observed_at: AwareDatetime | None = None
    source_uri: str | None = None
    call_id: str | None = None
    input_sha256: Sha256 | None = None
    output_sha256: Sha256 | None = None


class SemanticJudgeRequest(FrozenModel):
    schema_version: Literal[SEMANTIC_JUDGE_SCHEMA_VERSION] = SEMANTIC_JUDGE_SCHEMA_VERSION
    query_id: Identifier
    query: NonEmptyStr
    answer: NonEmptyStr
    claim_slate_sha256: Sha256
    claims: tuple[AtomicClaim, ...] = Field(min_length=1)
    evidence: tuple[EvidenceExcerpt, ...]
    evidence_completeness: EvidenceCompleteness
    truth_facts: tuple[TruthFact, ...]

    @model_validator(mode="after")
    def claim_ids_must_be_unique(self) -> SemanticJudgeRequest:
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("judge request claim ids must be unique")
        return self


class SemanticJudgeOutput(FrozenModel):
    claim_id: Identifier
    evidence_axis: EvidenceAxis
    truth_axis: TruthAxis
    label: VerdictLabel
    model_error_kind: ModelErrorKind | None = None
    evidence_ids: tuple[Identifier, ...] = ()
    truth_fact_ids: tuple[Identifier, ...] = ()
    quote: str | None = None
    error_type: Identifier | None = None
    severity: Severity
    evidence_sufficient: bool
    truth_sufficient: bool
    confidence: Probability
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def validate_axes_and_label(self) -> SemanticJudgeOutput:
        expected = _LABEL_BY_AXES.get(
            (self.evidence_axis, self.truth_axis),
            VerdictLabel.UNVERIFIED,
        )
        if self.label != expected:
            raise ValueError(
                f"label must be {expected.value} for the supplied evidence and truth axes"
            )
        if self.evidence_sufficient == (self.evidence_axis == EvidenceAxis.INSUFFICIENT):
            raise ValueError("evidence_sufficient conflicts with evidence_axis")
        if self.truth_sufficient == (self.truth_axis == TruthAxis.INSUFFICIENT):
            raise ValueError("truth_sufficient conflicts with truth_axis")
        if self.label == VerdictLabel.MODEL_ERROR and self.model_error_kind is None:
            raise ValueError("model_error requires model_error_kind")
        if self.label != VerdictLabel.MODEL_ERROR and self.model_error_kind is not None:
            raise ValueError("model_error_kind is only valid for model_error")
        return self


class JudgeIdentity(FrozenModel):
    judge_id: Identifier
    role: JudgeRole
    provider: NonEmptyStr
    model: NonEmptyStr
    deployment_version: NonEmptyStr
    prompt_sha256: Sha256
    same_family_as_evaluated_model: bool


class JudgeParseError(FrozenModel):
    line_number: int = Field(ge=1)
    code: Identifier
    detail: NonEmptyStr


class SemanticJudgeBatch(FrozenModel):
    schema_version: Literal[SEMANTIC_JUDGE_SCHEMA_VERSION] = SEMANTIC_JUDGE_SCHEMA_VERSION
    query_id: Identifier
    identity: JudgeIdentity
    status: BatchStatus
    outputs: tuple[SemanticJudgeOutput, ...]
    missing_claim_ids: tuple[Identifier, ...]
    unexpected_claim_ids: tuple[Identifier, ...]
    parse_errors: tuple[JudgeParseError, ...]
    raw_response_sha256: Sha256
    raw_response: str | None = None

    @model_validator(mode="after")
    def batch_status_matches_contents(self) -> SemanticJudgeBatch:
        output_ids = [output.claim_id for output in self.outputs]
        if len(output_ids) != len(set(output_ids)):
            raise ValueError("judge output claim ids must be unique")
        has_errors = bool(
            self.missing_claim_ids or self.unexpected_claim_ids or self.parse_errors
        )
        if self.status == BatchStatus.COMPLETE and has_errors:
            raise ValueError("complete batches cannot contain missing, unexpected, or parse errors")
        if self.status == BatchStatus.INVALID and self.outputs:
            raise ValueError("invalid batches cannot contain accepted outputs")
        return self
