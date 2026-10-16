"""Blind primary extraction followed by full-list review."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fincarat.io import sha256_file
from fincarat.judges import JudgeBackend
from fincarat.migrate import MigratedLegacyCase
from fincarat.schema import AtomicClaim, ClaimSlate, ExtractorRecord

from .parser import parse_claim_jsonl
from .schema import (
    AnswerUnitAnchor,
    ClaimExtractionBatch,
    ClaimExtractionRequest,
    ClaimExtractionRun,
    ExtractionMode,
    ExtractionRunStatus,
    ExtractionStatus,
)


def request_from_legacy_case(
    case: MigratedLegacyCase,
    *,
    mode: ExtractionMode = ExtractionMode.EXTRACT,
    candidate_claims: tuple[AtomicClaim, ...] = (),
) -> ClaimExtractionRequest:
    return ClaimExtractionRequest(
        mode=mode,
        query_id=case.query_id,
        query=case.prompt,
        answer=case.answer,
        answer_sha256=case.answer_sha256,
        as_of=case.as_of,
        answer_units=tuple(
            AnswerUnitAnchor(
                unit_id=unit.unit_id,
                text=unit.text,
                start=unit.span.start,
                end=unit.span.end,
            )
            for unit in case.answer_units
        ),
        candidate_claims=candidate_claims,
    )


def render_extraction_request(request: ClaimExtractionRequest) -> str:
    return json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


async def run_claim_extraction(
    backend: JudgeBackend,
    *,
    case: MigratedLegacyCase,
    primary_model: str,
    reviewer_model: str,
    prompt_path: Path,
    prompt_sha256: str,
    created_at: datetime,
    temperature: float = 0,
    max_tokens: int = 32000,
    single_pass: bool = False,
) -> ClaimExtractionRun:
    actual_sha256 = sha256_file(prompt_path)
    if actual_sha256 != prompt_sha256:
        raise ValueError(
            f"claim extractor prompt hash mismatch: {actual_sha256} != {prompt_sha256}"
        )
    system_prompt = prompt_path.read_text(encoding="utf-8")
    primary_request = request_from_legacy_case(case)
    primary_raw = await backend.complete(
        model=primary_model,
        system_prompt=system_prompt,
        user_prompt=render_extraction_request(primary_request),
        temperature=temperature,
        max_tokens=max_tokens,
    )
    primary = parse_claim_jsonl(
        primary_raw,
        request=primary_request,
        model=primary_model,
    )
    primary_attempts = [primary]
    if single_pass:
        if primary.status != ExtractionStatus.COMPLETE:
            repaired_raw = await backend.complete(
                model=primary_model,
                system_prompt=system_prompt,
                user_prompt=_repair_request(primary_request, primary),
                temperature=temperature,
                max_tokens=max_tokens,
            )
            primary = parse_claim_jsonl(
                repaired_raw,
                request=primary_request,
                model=primary_model,
            )
            primary_attempts.append(primary)
        if primary.status != ExtractionStatus.COMPLETE:
            return ClaimExtractionRun(
                query_id=case.query_id,
                status=ExtractionRunStatus.PRIMARY_FAILED,
                primary=primary,
                primary_attempts=tuple(primary_attempts),
            )
        slate = _build_slate(
            case=case,
            claims=primary.claims,
            primary_model=primary_model,
            reviewer_model=None,
            prompt_sha256=prompt_sha256,
            created_at=created_at,
        )
        return ClaimExtractionRun(
            query_id=case.query_id,
            status=ExtractionRunStatus.COMPLETE,
            primary=primary,
            primary_attempts=tuple(primary_attempts),
            claim_slate=slate,
        )

    if primary.status == ExtractionStatus.COMPLETE:
        review_request = request_from_legacy_case(
            case,
            mode=ExtractionMode.REVIEW,
            candidate_claims=primary.claims,
        )
        review_prompt = render_extraction_request(review_request)
    else:
        review_request = primary_request
        review_prompt = _repair_request(primary_request, primary)
    review_raw = await backend.complete(
        model=reviewer_model,
        system_prompt=system_prompt,
        user_prompt=review_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    review = parse_claim_jsonl(
        review_raw,
        request=review_request,
        model=reviewer_model,
    )
    review_attempts = [review]
    if review.status != ExtractionStatus.COMPLETE:
        repaired_raw = await backend.complete(
            model=reviewer_model,
            system_prompt=system_prompt,
            user_prompt=_repair_request(review_request, review),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        review = parse_claim_jsonl(
            repaired_raw,
            request=review_request,
            model=reviewer_model,
        )
        review_attempts.append(review)
    if review.status != ExtractionStatus.COMPLETE:
        return ClaimExtractionRun(
            query_id=case.query_id,
            status=ExtractionRunStatus.REVIEW_FAILED,
            primary=primary,
            primary_attempts=tuple(primary_attempts),
            review=review,
            review_attempts=tuple(review_attempts),
        )

    slate = _build_slate(
        case=case,
        claims=review.claims,
        primary_model=primary_model,
        reviewer_model=reviewer_model,
        prompt_sha256=prompt_sha256,
        created_at=created_at,
    )
    return ClaimExtractionRun(
        query_id=case.query_id,
        status=ExtractionRunStatus.COMPLETE,
        primary=primary,
        primary_attempts=tuple(primary_attempts),
        review=review,
        review_attempts=tuple(review_attempts),
        claim_slate=slate,
    )


def _build_slate(
    *,
    case: MigratedLegacyCase,
    claims: tuple[AtomicClaim, ...],
    primary_model: str,
    reviewer_model: str | None,
    prompt_sha256: str,
    created_at: datetime,
) -> ClaimSlate:
    return ClaimSlate(
        claim_slate_version="slate-v2-pilot-v1",
        query_id=case.query_id,
        created_at=created_at,
        extractor=ExtractorRecord(
            model=primary_model,
            prompt_sha256=prompt_sha256,
            reviewer_model=reviewer_model,
        ),
        answer_sha256=case.answer_sha256,
        claims=claims,
    )


def _repair_request(
    request: ClaimExtractionRequest,
    failed: ClaimExtractionBatch,
) -> str:
    payload = {
        "instruction": (
            "Repair the previous output. Return compact JSONL only: one complete "
            "claim object per line, no markdown. Use is_key_claim, not is_claim. "
            "Fix every validation error; do not explain the changes."
        ),
        "request": request.model_dump(mode="json"),
        "validation_errors": [
            error.model_dump(mode="json") for error in failed.errors
        ],
        "previous_output": failed.raw_response,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
