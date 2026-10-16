"""Parse judge JSONL without silently converting failures into support."""

from __future__ import annotations

import hashlib
import json

from pydantic import ValidationError

from fincarat.schema import EvidenceCompleteness, ModelErrorKind

from .schema import (
    BatchStatus,
    JudgeIdentity,
    JudgeParseError,
    SemanticJudgeBatch,
    SemanticJudgeOutput,
    SemanticJudgeRequest,
)


def parse_judge_jsonl(
    raw_response: str,
    *,
    request: SemanticJudgeRequest,
    identity: JudgeIdentity,
) -> SemanticJudgeBatch:
    expected_ids = {claim.claim_id for claim in request.claims}
    evidence_ids = {item.evidence_id for item in request.evidence}
    truth_fact_ids = {fact.fact_id for fact in request.truth_facts}
    accepted: dict[str, SemanticJudgeOutput] = {}
    unexpected: set[str] = set()
    errors: list[JudgeParseError] = []

    for line_number, line in enumerate(raw_response.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(
                JudgeParseError(
                    line_number=line_number,
                    code="judge.invalid_json",
                    detail=str(exc),
                )
            )
            continue
        try:
            output = SemanticJudgeOutput.model_validate(payload)
        except ValidationError as exc:
            errors.append(
                JudgeParseError(
                    line_number=line_number,
                    code="judge.invalid_schema",
                    detail=str(exc),
                )
            )
            continue
        if output.claim_id not in expected_ids:
            unexpected.add(output.claim_id)
            errors.append(
                JudgeParseError(
                    line_number=line_number,
                    code="judge.unexpected_claim",
                    detail=f"Unexpected claim id: {output.claim_id}",
                )
            )
            continue
        if output.claim_id in accepted:
            errors.append(
                JudgeParseError(
                    line_number=line_number,
                    code="judge.duplicate_claim",
                    detail=f"Duplicate claim id: {output.claim_id}",
                )
            )
            continue

        unknown_evidence = set(output.evidence_ids) - evidence_ids
        unknown_truth = set(output.truth_fact_ids) - truth_fact_ids
        if unknown_evidence or unknown_truth:
            errors.append(
                JudgeParseError(
                    line_number=line_number,
                    code="judge.unknown_reference",
                    detail=(
                        f"Unknown evidence ids: {sorted(unknown_evidence)}; "
                        f"unknown truth fact ids: {sorted(unknown_truth)}"
                    ),
                )
            )
            continue
        if (
            output.model_error_kind == ModelErrorKind.FABRICATED
            and request.evidence_completeness != EvidenceCompleteness.COMPLETE
        ):
            errors.append(
                JudgeParseError(
                    line_number=line_number,
                    code="judge.fabrication_without_observability",
                    detail="fabricated is forbidden unless evidence observability is complete",
                )
            )
            continue
        accepted[output.claim_id] = output

    missing = expected_ids - set(accepted)
    if accepted and not missing and not unexpected and not errors:
        status = BatchStatus.COMPLETE
    elif accepted:
        status = BatchStatus.PARTIAL
    else:
        status = BatchStatus.INVALID
    return SemanticJudgeBatch(
        query_id=request.query_id,
        identity=identity,
        status=status,
        outputs=tuple(
            accepted[claim.claim_id]
            for claim in request.claims
            if claim.claim_id in accepted
        ),
        missing_claim_ids=tuple(sorted(missing)),
        unexpected_claim_ids=tuple(sorted(unexpected)),
        parse_errors=tuple(errors),
        raw_response_sha256=hashlib.sha256(raw_response.encode("utf-8")).hexdigest(),
        raw_response=raw_response,
    )
