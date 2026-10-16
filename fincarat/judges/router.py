"""Risk-based review routing and conflict-preserving resolution."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from fincarat.checkers import CheckStatus, DeterministicAssessment
from fincarat.schema import (
    AtomicClaim,
    ClaimType,
    EvidenceAxis,
    FrozenModel,
    ModelErrorKind,
    TruthAxis,
    UnverifiedReason,
    VerdictLabel,
    Verifiability,
)
from fincarat.schema.common import Probability

from .schema import JudgeRole, SemanticJudgeOutput


class RouteTarget(StrEnum):
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"
    EXPRESSION_REVIEW = "expression_review"


class RoutingReason(StrEnum):
    CLAIM_TYPE = "claim_type"
    KEY_CLAIM = "key_claim"
    LOW_CONFIDENCE = "low_confidence"
    INSUFFICIENT_MATERIAL = "insufficient_material"
    SOURCE_CONFLICT = "source_conflict"
    SAME_MODEL_FAMILY = "same_model_family"
    PRIMARY_MISSING = "primary_missing"


class RoutingDecision(FrozenModel):
    target: RouteTarget
    judge_roles: tuple[JudgeRole, ...]
    reasons: tuple[RoutingReason, ...] = Field(min_length=1)


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNVERIFIED = "unverified"


class ProvisionalResolution(FrozenModel):
    status: ResolutionStatus
    evidence_axis: EvidenceAxis
    truth_axis: TruthAxis
    label: VerdictLabel
    model_error_kind: ModelErrorKind | None = None
    unverified_reason: UnverifiedReason | None = None
    needs_human_review: bool
    rationale: str


class ReviewRouter:
    def __init__(self, *, low_confidence_threshold: Probability = 0.8) -> None:
        if not 0 <= low_confidence_threshold <= 1:
            raise ValueError("low_confidence_threshold must be within [0, 1]")
        self.low_confidence_threshold = low_confidence_threshold

    def initial(self, claim: AtomicClaim) -> RoutingDecision:
        if claim.verifiability == Verifiability.DETERMINISTIC or claim.claim_type in {
            ClaimType.NUMERIC_FACT,
            ClaimType.DERIVED_NUMERIC,
        }:
            return RoutingDecision(
                target=RouteTarget.DETERMINISTIC,
                judge_roles=(),
                reasons=(RoutingReason.CLAIM_TYPE,),
            )
        target = (
            RouteTarget.EXPRESSION_REVIEW
            if claim.verifiability == Verifiability.NOT_VERIFIABLE
            else RouteTarget.SEMANTIC
        )
        roles = [JudgeRole.PRIMARY]
        reasons = [RoutingReason.CLAIM_TYPE]
        if claim.is_key_claim:
            roles.append(JudgeRole.STRONG_REVIEW)
            reasons.append(RoutingReason.KEY_CLAIM)
        return RoutingDecision(target=target, judge_roles=tuple(roles), reasons=tuple(reasons))

    def after_primary(
        self,
        claim: AtomicClaim,
        primary: SemanticJudgeOutput | None,
        *,
        source_conflict: bool = False,
        primary_same_family: bool = False,
    ) -> RoutingDecision:
        initial = self.initial(claim)
        roles = list(initial.judge_roles)
        reasons = list(initial.reasons)
        if primary is None:
            _append_unique(roles, JudgeRole.STRONG_REVIEW)
            _append_unique(roles, JudgeRole.HETEROGENEOUS_REVIEW)
            reasons.append(RoutingReason.PRIMARY_MISSING)
        else:
            if primary.confidence < self.low_confidence_threshold:
                _append_unique(roles, JudgeRole.STRONG_REVIEW)
                _append_unique(roles, JudgeRole.HETEROGENEOUS_REVIEW)
                reasons.append(RoutingReason.LOW_CONFIDENCE)
            if (
                primary.evidence_axis == EvidenceAxis.INSUFFICIENT
                or primary.truth_axis == TruthAxis.INSUFFICIENT
            ):
                _append_unique(roles, JudgeRole.STRONG_REVIEW)
                _append_unique(roles, JudgeRole.HETEROGENEOUS_REVIEW)
                reasons.append(RoutingReason.INSUFFICIENT_MATERIAL)
        if source_conflict:
            _append_unique(roles, JudgeRole.STRONG_REVIEW)
            _append_unique(roles, JudgeRole.HETEROGENEOUS_REVIEW)
            reasons.append(RoutingReason.SOURCE_CONFLICT)
        if primary_same_family:
            _append_unique(roles, JudgeRole.HETEROGENEOUS_REVIEW)
            reasons.append(RoutingReason.SAME_MODEL_FAMILY)
        return RoutingDecision(
            target=initial.target,
            judge_roles=tuple(roles),
            reasons=tuple(dict.fromkeys(reasons)),
        )


def resolve_semantic(outputs: tuple[SemanticJudgeOutput, ...]) -> ProvisionalResolution:
    if not outputs:
        return _unverified(UnverifiedReason.JUDGE_MISSING, "No valid judge output.")
    signatures = {
        (
            output.evidence_axis,
            output.truth_axis,
            output.label,
            output.model_error_kind,
        )
        for output in outputs
    }
    if len(signatures) != 1:
        return _unverified(
            UnverifiedReason.JUDGE_DISAGREEMENT,
            "Judge outputs conflict; no majority override was applied.",
        )
    output = outputs[0]
    if (
        output.evidence_axis == EvidenceAxis.INSUFFICIENT
        or output.truth_axis == TruthAxis.INSUFFICIENT
    ):
        return _unverified(
            UnverifiedReason.INSUFFICIENT_EVIDENCE,
            "At least one truth axis lacks sufficient material.",
            evidence_axis=output.evidence_axis,
            truth_axis=output.truth_axis,
        )
    return ProvisionalResolution(
        status=ResolutionStatus.RESOLVED,
        evidence_axis=output.evidence_axis,
        truth_axis=output.truth_axis,
        label=output.label,
        model_error_kind=output.model_error_kind,
        needs_human_review=False,
        rationale="All available semantic reviews agree on both axes.",
    )


def resolve_deterministic(
    evidence: DeterministicAssessment,
    truth: DeterministicAssessment,
) -> ProvisionalResolution:
    if evidence.claim_id != truth.claim_id:
        raise ValueError("evidence and truth assessments must refer to the same claim")
    evidence_axis = _evidence_axis(evidence.status)
    truth_axis = _truth_axis(truth.status)
    if EvidenceAxis.INSUFFICIENT == evidence_axis or TruthAxis.INSUFFICIENT == truth_axis:
        return _unverified(
            UnverifiedReason.INSUFFICIENT_EVIDENCE,
            "A deterministic axis could not produce a strong result.",
            evidence_axis=evidence_axis,
            truth_axis=truth_axis,
        )
    mapping = {
        (EvidenceAxis.SUPPORTED, TruthAxis.CORRECT): VerdictLabel.SUPPORTED,
        (EvidenceAxis.NOT_SUPPORTED, TruthAxis.CORRECT): VerdictLabel.UNSUPPORTED_BUT_TRUE,
        (EvidenceAxis.SUPPORTED, TruthAxis.INCORRECT): VerdictLabel.SOURCE_ERROR,
        (EvidenceAxis.NOT_SUPPORTED, TruthAxis.INCORRECT): VerdictLabel.MODEL_ERROR,
    }
    label = mapping[(evidence_axis, truth_axis)]
    return ProvisionalResolution(
        status=ResolutionStatus.RESOLVED,
        evidence_axis=evidence_axis,
        truth_axis=truth_axis,
        label=label,
        model_error_kind=(
            ModelErrorKind.CONTRADICTED if label == VerdictLabel.MODEL_ERROR else None
        ),
        needs_human_review=False,
        rationale="Independent deterministic evidence and truth checks were combined.",
    )


def _evidence_axis(status: CheckStatus) -> EvidenceAxis:
    if status == CheckStatus.PASS:
        return EvidenceAxis.SUPPORTED
    if status == CheckStatus.FAIL:
        return EvidenceAxis.NOT_SUPPORTED
    return EvidenceAxis.INSUFFICIENT


def _truth_axis(status: CheckStatus) -> TruthAxis:
    if status == CheckStatus.PASS:
        return TruthAxis.CORRECT
    if status == CheckStatus.FAIL:
        return TruthAxis.INCORRECT
    return TruthAxis.INSUFFICIENT


def _unverified(
    reason: UnverifiedReason,
    rationale: str,
    *,
    evidence_axis: EvidenceAxis = EvidenceAxis.INSUFFICIENT,
    truth_axis: TruthAxis = TruthAxis.INSUFFICIENT,
) -> ProvisionalResolution:
    return ProvisionalResolution(
        status=ResolutionStatus.UNVERIFIED,
        evidence_axis=evidence_axis,
        truth_axis=truth_axis,
        label=VerdictLabel.UNVERIFIED,
        unverified_reason=reason,
        needs_human_review=True,
        rationale=rationale,
    )


def _append_unique(items: list[JudgeRole], value: JudgeRole) -> None:
    if value not in items:
        items.append(value)
