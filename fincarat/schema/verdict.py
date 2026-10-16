"""Evidence × truth verdicts with explicit abstention states."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .common import FrozenModel, Identifier, NonEmptyStr, Probability, Sha256

VERDICT_SET_SCHEMA_VERSION = "fincarat-verdict-set-v1"


class EvidenceAxis(StrEnum):
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    INSUFFICIENT = "insufficient"


class TruthAxis(StrEnum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    INSUFFICIENT = "insufficient"


class VerdictLabel(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED_BUT_TRUE = "unsupported_but_true"
    SOURCE_ERROR = "source_error"
    MODEL_ERROR = "model_error"
    UNVERIFIED = "unverified"


class ModelErrorKind(StrEnum):
    CONTRADICTED = "contradicted"
    FABRICATED = "fabricated"


class UnverifiedReason(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    JUDGE_DISAGREEMENT = "judge_disagreement"
    OBSERVABILITY_LIMITED = "observability_limited"
    BELOW_CONFIRMATION_THRESHOLD = "below_confirmation_threshold"
    JUDGE_MISSING = "judge_missing"


class EvidenceCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class DecisionSource(StrEnum):
    DETERMINISTIC = "deterministic"
    SEMANTIC_JUDGE = "semantic_judge"
    AGENTIC_VERIFIER = "agentic_verifier"
    RISK_CALIBRATED = "risk_calibrated"
    HUMAN = "human"
    ADJUDICATION = "adjudication"


_CORE_MAPPING = {
    (EvidenceAxis.SUPPORTED, TruthAxis.CORRECT): VerdictLabel.SUPPORTED,
    (EvidenceAxis.NOT_SUPPORTED, TruthAxis.CORRECT): VerdictLabel.UNSUPPORTED_BUT_TRUE,
    (EvidenceAxis.SUPPORTED, TruthAxis.INCORRECT): VerdictLabel.SOURCE_ERROR,
    (EvidenceAxis.NOT_SUPPORTED, TruthAxis.INCORRECT): VerdictLabel.MODEL_ERROR,
}


class ClaimVerdict(FrozenModel):
    claim_id: Identifier
    evidence_axis: EvidenceAxis
    truth_axis: TruthAxis
    label: VerdictLabel
    model_error_kind: ModelErrorKind | None = None
    unverified_reason: UnverifiedReason | None = None
    evidence_completeness: EvidenceCompleteness
    evidence_ids: tuple[Identifier, ...] = ()
    truth_fact_ids: tuple[Identifier, ...] = ()
    decision_source: DecisionSource
    confidence: Probability
    rationale: NonEmptyStr
    decided_at: AwareDatetime
    readjudicated: bool = False

    @model_validator(mode="after")
    def enforce_state_machine(self) -> ClaimVerdict:
        expected = _CORE_MAPPING.get((self.evidence_axis, self.truth_axis), VerdictLabel.UNVERIFIED)
        if self.label != expected:
            raise ValueError(
                "label does not match evidence × truth state: "
                f"expected {expected.value}, got {self.label.value}"
            )
        if self.label == VerdictLabel.MODEL_ERROR:
            if self.model_error_kind is None:
                raise ValueError("model_error requires model_error_kind")
            if (
                self.model_error_kind == ModelErrorKind.FABRICATED
                and self.evidence_completeness != EvidenceCompleteness.COMPLETE
            ):
                raise ValueError("fabricated requires complete evidence observability")
        elif self.model_error_kind is not None:
            raise ValueError("model_error_kind is only valid for model_error")

        if self.label == VerdictLabel.UNVERIFIED and self.unverified_reason is None:
            raise ValueError("unverified requires unverified_reason")
        if self.label != VerdictLabel.UNVERIFIED and self.unverified_reason is not None:
            raise ValueError("unverified_reason is only valid for unverified")
        return self


class VerdictSet(FrozenModel):
    schema_version: Literal[VERDICT_SET_SCHEMA_VERSION] = VERDICT_SET_SCHEMA_VERSION
    verdict_set_version: Identifier
    query_id: Identifier
    claim_slate_sha256: Sha256
    verdicts: tuple[ClaimVerdict, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def verdict_claim_ids_must_be_unique(self) -> VerdictSet:
        claim_ids = [verdict.claim_id for verdict in self.verdicts]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("verdict claim ids must be unique")
        return self
