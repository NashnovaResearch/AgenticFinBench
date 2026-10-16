"""Resume claim extraction across token-limit cutoffs.

A 32k response that still parses some claims is not a finished slate when the
model hit max_tokens. Later rounds keep accepted claims and ask only for the
remainder. They do not replay the truncated raw dump.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fincarat.schema import AtomicClaim

from .parser import parse_claim_jsonl
from .runner import _repair_request, render_extraction_request
from .schema import ClaimExtractionBatch, ClaimExtractionRequest, ExtractionError

_CUTOFF_FINISH_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})
_TRUNCATED_CODES = frozenset({"extract.truncated_tail_skipped"})
DEFAULT_LONG_ANSWER_CHARS = 4000


def extraction_effort(answer: str, *, long_char_threshold: int = DEFAULT_LONG_ANSWER_CHARS) -> str:
    return "low" if len(answer) > long_char_threshold else "high"


def extraction_thinking_extra_body(
    model: str,
    answer: str,
    *,
    long_char_threshold: int = DEFAULT_LONG_ANSWER_CHARS,
) -> dict[str, Any] | None:
    """Keep Opus thinking on; use low effort only for long answers.

    Thinking tokens still share max_tokens with the JSON. effort is a soft cap,
    not thinking.type=disabled.
    """
    if not model.casefold().startswith("anthropic/"):
        return None
    effort = extraction_effort(answer, long_char_threshold=long_char_threshold)
    thinking = {"type": "adaptive", "display": "summarized"}
    return {
        "thinking": thinking,
        "output_config": {"effort": effort},
        "providerOptions": {"anthropic": {"thinking": thinking, "effort": effort}},
    }


@dataclass(frozen=True, slots=True)
class ContinuedExtraction:
    complete: bool
    claims: tuple[AtomicClaim, ...]
    rounds: tuple[dict[str, Any], ...]
    last_raw: str
    last_finish_reason: str | None
    stall_reason: str | None = None


def extraction_was_cut_off(
    batch: ClaimExtractionBatch,
    finish_reason: str | None,
) -> bool:
    reason = (finish_reason or "").strip().casefold()
    if reason in _CUTOFF_FINISH_REASONS:
        return True
    return any(item.code in _TRUNCATED_CODES for item in batch.normalizations)


def merge_extracted_claims(
    query_id: str,
    *groups: tuple[AtomicClaim, ...] | list[AtomicClaim],
) -> tuple[AtomicClaim, ...]:
    merged: list[AtomicClaim] = []
    seen: set[tuple[object, ...]] = set()
    for group in groups:
        for claim in group:
            key = (
                claim.answer_span.unit_id,
                claim.answer_span.start,
                claim.answer_span.end,
                claim.claim_text.strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(claim)
    merged.sort(
        key=lambda claim: (
            claim.answer_span.start,
            claim.answer_span.end,
            claim.claim_text,
        )
    )
    return tuple(
        claim.model_copy(update={"claim_id": f"{query_id}-c{index:03d}"})
        for index, claim in enumerate(merged, start=1)
    )


def continue_extraction_request(
    request: ClaimExtractionRequest,
    accepted: tuple[AtomicClaim, ...],
    *,
    round_index: int,
) -> str:
    last = accepted[-1] if accepted else None
    next_index = len(accepted) + 1
    next_id = f"{request.query_id}-c{next_index:03d}"
    if accepted:
        instruction = (
            "Continue extraction. The previous response was cut off at the output "
            "token limit. Return compact JSONL only: one complete NEW claim object "
            "per line, no markdown, no wrapping array. Do not repeat claims already "
            f"accepted. Number new claims sequentially starting at {next_id}. "
            "Cover remaining factual assertions after the last accepted answer_span. "
            "If nothing remains, return no objects."
        )
    else:
        instruction = (
            "The previous response was cut off before any valid claim was parsed. "
            "Start extraction from the beginning. Return compact JSONL only: one "
            "complete claim object per line, no markdown, no wrapping array. "
            f"Number claims sequentially starting at {next_id}."
        )
    payload = {
        "instruction": instruction,
        "round": round_index,
        "accepted_count": len(accepted),
        "next_claim_id": next_id,
        "last_accepted": None
        if last is None
        else {
            "claim_id": last.claim_id,
            "claim_text": last.claim_text,
            "answer_span": last.answer_span.model_dump(mode="json"),
        },
        "accepted_spans": [
            {
                "claim_id": claim.claim_id,
                "claim_text": claim.claim_text,
                "answer_span": claim.answer_span.model_dump(mode="json"),
            }
            for claim in accepted
        ],
        "request": request.model_dump(mode="json"),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


async def _complete_round(
    backend: Any,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    extra_body: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    detailed = getattr(backend, "complete_detailed", None)
    if callable(detailed):
        result = await detailed(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        content = getattr(result, "content", None)
        finish_reason = getattr(result, "finish_reason", None)
        return ("" if content is None else str(content), finish_reason)
    content = await backend.complete(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return str(content or ""), None


async def extract_with_continuation(
    backend: Any,
    *,
    request: ClaimExtractionRequest,
    system_prompt: str,
    model: str,
    temperature: float = 0,
    max_tokens: int = 32000,
    max_rounds: int = 12,
    long_char_threshold: int = DEFAULT_LONG_ANSWER_CHARS,
) -> ContinuedExtraction:
    if max_rounds < 1:
        raise ValueError("max_rounds must be at least 1")
    extra_body = extraction_thinking_extra_body(
        model, request.answer, long_char_threshold=long_char_threshold
    )
    effort = extraction_effort(request.answer, long_char_threshold=long_char_threshold)
    accepted: tuple[AtomicClaim, ...] = ()
    rounds: list[dict[str, Any]] = []
    last_raw = ""
    last_finish: str | None = None
    last_batch: ClaimExtractionBatch | None = None
    pending_repair: ClaimExtractionBatch | None = None
    stall_reason: str | None = None
    cut_off = False

    for round_index in range(1, max_rounds + 1):
        used_repair = False
        if pending_repair is not None:
            user_prompt = _repair_request(request, pending_repair)
            pending_repair = None
            used_repair = True
        elif round_index == 1:
            user_prompt = render_extraction_request(request)
        else:
            user_prompt = continue_extraction_request(
                request, accepted, round_index=round_index
            )
        last_raw, last_finish = await _complete_round(
            backend,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        last_batch = parse_claim_jsonl(last_raw, request=request, model=model)
        cut_off = extraction_was_cut_off(last_batch, last_finish)
        before = len(accepted)
        accepted = merge_extracted_claims(request.query_id, accepted, last_batch.claims)
        added = len(accepted) - before
        rounds.append(
            {
                "round": round_index,
                "finish_reason": last_finish,
                "parsed": len(last_batch.claims),
                "added": added,
                "total": len(accepted),
                "cut_off": cut_off,
                "repair": used_repair,
                "effort": effort if extra_body else None,
                "truncated_tail": any(
                    item.code in _TRUNCATED_CODES for item in last_batch.normalizations
                ),
            }
        )
        if cut_off:
            if added == 0 and round_index > 1:
                stall_reason = "continuation_stalled"
                break
            continue
        if not accepted and round_index == 1 and last_batch is not None:
            pending_repair = last_batch
            continue
        stall_reason = None
        break
    else:
        if cut_off:
            stall_reason = stall_reason or "max_rounds"

    complete = bool(accepted) and not cut_off and stall_reason is None
    if not accepted and stall_reason is None:
        stall_reason = "empty"
    return ContinuedExtraction(
        complete=complete,
        claims=accepted,
        rounds=tuple(rounds),
        last_raw=last_raw,
        last_finish_reason=last_finish,
        stall_reason=stall_reason,
    )


def continuation_errors(result: ContinuedExtraction) -> list[ExtractionError]:
    if result.complete:
        return []
    detail = result.stall_reason or "incomplete"
    return [
        ExtractionError(
            line_number=1,
            code="extract.continuation_incomplete",
            detail=detail,
        )
    ]
