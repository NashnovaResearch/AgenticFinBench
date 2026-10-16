"""Strict parser for atomic-claim JSONL, with recovery for messy model output."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from fincarat.schema import AnswerSpan, AtomicClaim

from .schema import (
    ClaimExtractionBatch,
    ClaimExtractionRequest,
    ExtractionError,
    ExtractionStatus,
)

_CLAIM_FIELDS = frozenset(AtomicClaim.model_fields)
_FIELD_ALIASES = {
    "is_claim": "is_key_claim",
    "isKeyClaim": "is_key_claim",
    "key_claim": "is_key_claim",
    "claimType": "claim_type",
    "claimText": "claim_text",
    "claimId": "claim_id",
    "answerSpan": "answer_span",
}
_WRAPPER_KEYS = ("claims", "results", "data", "items")


def parse_claim_jsonl(
    raw_response: str,
    *,
    request: ClaimExtractionRequest,
    model: str,
) -> ClaimExtractionBatch:
    claims: list[AtomicClaim] = []
    faults: list[ExtractionError] = []
    normalizations: list[ExtractionError] = []
    anchors = {unit.unit_id: unit for unit in request.answer_units}

    payloads = _iter_claim_payloads(raw_response, faults=faults, normalizations=normalizations)
    for index, payload in enumerate(payloads, start=1):
        normalized, notes = _normalize_claim_payload(payload)
        normalizations.extend(
            ExtractionError(line_number=index, code=code, detail=detail) for code, detail in notes
        )
        try:
            if (
                isinstance(normalized, dict)
                and normalized.get("claim_type") in {"numeric_fact", "derived_numeric"}
                and normalized.get("verifiability") != "deterministic"
            ):
                normalized["verifiability"] = "deterministic"
                normalizations.append(
                    ExtractionError(
                        line_number=index,
                        code="extract.numeric_route_normalized",
                        detail="Numeric claim routing was normalized to deterministic.",
                    )
                )
            if "is_key_claim" not in normalized:
                normalized["is_key_claim"] = True
                normalizations.append(
                    ExtractionError(
                        line_number=index,
                        code="extract.is_key_claim_defaulted",
                        detail="Missing is_key_claim was defaulted to true.",
                    )
                )
            claim = AtomicClaim.model_validate(normalized)
        except ValidationError as exc:
            faults.append(
                ExtractionError(
                    line_number=index,
                    code="extract.invalid_schema",
                    detail=str(exc),
                )
            )
            continue

        anchor = anchors.get(claim.answer_span.unit_id)
        if anchor is None:
            faults.append(
                ExtractionError(
                    line_number=index,
                    code="extract.unknown_answer_unit",
                    detail=f"Unknown answer unit: {claim.answer_span.unit_id}",
                )
            )
            continue
        if claim.answer_span.start < anchor.start or claim.answer_span.end > anchor.end:
            unit_length = anchor.end - anchor.start
            if 0 <= claim.answer_span.start < claim.answer_span.end <= unit_length:
                claim = claim.model_copy(
                    update={
                        "answer_span": AnswerSpan(
                            unit_id=anchor.unit_id,
                            start=anchor.start + claim.answer_span.start,
                            end=anchor.start + claim.answer_span.end,
                        )
                    }
                )
                normalizations.append(
                    ExtractionError(
                        line_number=index,
                        code="extract.span_shifted_from_unit_local",
                        detail=(
                            f"Shifted unit-local offsets for {anchor.unit_id} "
                            "to global offsets."
                        ),
                    )
                )
            else:
                faults.append(
                    ExtractionError(
                        line_number=index,
                        code="extract.span_outside_unit",
                        detail=f"Claim span is outside answer unit {anchor.unit_id}",
                    )
                )
                continue
        claims.append(claim)

    claim_ids = [claim.claim_id for claim in claims]
    expected_ids = [f"{request.query_id}-c{index:03d}" for index in range(1, len(claims) + 1)]
    if claims and claim_ids != expected_ids:
        claims = [
            claim.model_copy(update={"claim_id": expected_id})
            for claim, expected_id in zip(claims, expected_ids, strict=True)
        ]
        normalizations.append(
            ExtractionError(
                line_number=1,
                code="extract.claim_id_sequence_normalized",
                detail="Renumbered claims sequentially in answer order.",
            )
        )

    if claims:
        status = ExtractionStatus.COMPLETE
        accepted = tuple(claims)
        errors: tuple[ExtractionError, ...] = ()
        if faults:
            normalizations.extend(
                ExtractionError(
                    line_number=item.line_number,
                    code="extract.skipped_invalid_claim",
                    detail=f"{item.code}: {item.detail}",
                )
                for item in faults
            )
    else:
        status = ExtractionStatus.INVALID
        accepted = ()
        if not faults:
            faults.append(
                ExtractionError(
                    line_number=1,
                    code="extract.empty",
                    detail="Extractor returned no claims.",
                )
            )
        errors = tuple(faults)

    return ClaimExtractionBatch(
        query_id=request.query_id,
        model=model,
        status=status,
        claims=accepted,
        errors=errors,
        normalizations=tuple(normalizations),
        raw_response_sha256=hashlib.sha256(raw_response.encode("utf-8")).hexdigest(),
        raw_response=raw_response,
    )


def _iter_claim_payloads(
    raw_response: str,
    *,
    faults: list[ExtractionError],
    normalizations: list[ExtractionError],
) -> list[dict[str, Any]]:
    text = _strip_markdown_fence(raw_response)
    if text != raw_response.strip():
        normalizations.append(
            ExtractionError(
                line_number=1,
                code="extract.markdown_fence_stripped",
                detail="Removed a markdown code fence around the claim list.",
            )
        )
    values: list[Any] = []
    try:
        values = _flatten_loaded(json.loads(text))
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        index = 0
        while index < len(text):
            while index < len(text) and text[index] not in "{[":
                index += 1
            if index >= len(text):
                break
            try:
                value, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError as exc:
                if values:
                    normalizations.append(
                        ExtractionError(
                            line_number=max(len(values), 1),
                            code="extract.truncated_tail_skipped",
                            detail=str(exc),
                        )
                    )
                    break
                index += 1
                continue
            values.extend(_flatten_loaded(value))
            index = end
    payloads = [item for item in values if isinstance(item, dict)]
    if not payloads and text.strip() and not faults:
        faults.append(
            ExtractionError(
                line_number=1,
                code="extract.invalid_json",
                detail="Extractor JSON did not contain claim objects.",
            )
        )
    return payloads


def _strip_markdown_fence(raw_response: str) -> str:
    text = raw_response.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _flatten_loaded(loaded: Any) -> list[Any]:
    if isinstance(loaded, list):
        flattened: list[Any] = []
        for item in loaded:
            flattened.extend(_flatten_loaded(item))
        return flattened
    if not isinstance(loaded, dict):
        return []
    for key in _WRAPPER_KEYS:
        nested = loaded.get(key)
        if isinstance(nested, list):
            return _flatten_loaded(nested)
    return [loaded]


def _normalize_claim_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    notes: list[tuple[str, str]] = []
    normalized = dict(payload)
    for source, target in _FIELD_ALIASES.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized.pop(source)
            notes.append(
                (
                    "extract.field_alias_normalized",
                    f"Renamed {source} to {target}.",
                )
            )
        elif source in normalized:
            normalized.pop(source)
            notes.append(
                (
                    "extract.extra_fields_dropped",
                    f"Dropped duplicate alias field {source}.",
                )
            )
    extras = [key for key in list(normalized) if key not in _CLAIM_FIELDS]
    for key in extras:
        normalized.pop(key)
        notes.append(("extract.extra_fields_dropped", f"Dropped extra field {key}."))
    subject = normalized.get("subject")
    if isinstance(subject, str) and subject.strip():
        normalized["subject"] = {"name": subject.strip()}
        notes.append(
            (
                "extract.subject_object_normalized",
                "Coerced a string subject into {name: ...}.",
            )
        )
    return normalized, notes
