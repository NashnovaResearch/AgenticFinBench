"""Provider-neutral semantic judge runner with an OpenAI-compatible backend."""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from openai import AsyncOpenAI

from fincarat.io import sha256_file

from .parser import parse_judge_jsonl
from .schema import JudgeIdentity, SemanticJudgeBatch, SemanticJudgeRequest

usage_sink: ContextVar[list["CompletionUsage"] | None] = ContextVar(
    "fincarat_usage_sink",
    default=None,
)


class JudgeBackend(Protocol):
    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class CompletionUsage:
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float | None = None


@dataclass(frozen=True, slots=True)
class CompletionResult:
    content: str
    finish_reason: str | None = None


class OpenAICompatibleJudgeBackend:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = 1,
    ) -> None:
        if not api_key.strip():
            raise ValueError("judge api_key must not be empty")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self.usage_records: list[CompletionUsage] = []
        self.request_count = 0

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        result = await self.complete_detailed(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not result.content:
            raise RuntimeError(
                f"judge returned empty content; finish_reason={result.finish_reason or 'unknown'}"
            )
        return result.content

    async def complete_detailed(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        extra_body: dict[str, Any] | None = None,
    ) -> CompletionResult:
        self.request_count += 1
        body = extra_body
        if body is None:
            lowered = model.casefold()
            if lowered.startswith(("deepseek/", "deepseek-", "zai/", "glm-")):
                body = {
                    "thinking": {"type": "disabled"},
                    "reasoning": {"effort": "none"},
                }
        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=body,
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        if usage is not None:
            record = CompletionUsage(
                model=model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                cost=_usage_cost(usage),
            )
            self.usage_records.append(record)
            sink = usage_sink.get()
            if sink is not None:
                sink.append(record)
        return CompletionResult(
            content=content,
            finish_reason=response.choices[0].finish_reason,
        )


def _usage_cost(usage: object) -> float | None:
    cost = getattr(usage, "cost", None)
    if cost is not None:
        return float(cost)
    extra = getattr(usage, "model_extra", None)
    if isinstance(extra, dict) and extra.get("cost") is not None:
        return float(extra["cost"])
    return None


def render_request(request: SemanticJudgeRequest) -> str:
    payload = request.model_dump(mode="json")
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


async def run_semantic_judge(
    backend: JudgeBackend,
    *,
    request: SemanticJudgeRequest,
    identity: JudgeIdentity,
    prompt_path: Path,
    temperature: float,
    max_tokens: int,
) -> SemanticJudgeBatch:
    actual_prompt_sha256 = sha256_file(prompt_path)
    if actual_prompt_sha256 != identity.prompt_sha256:
        raise ValueError(
            "judge prompt hash does not match frozen identity: "
            f"{actual_prompt_sha256} != {identity.prompt_sha256}"
        )
    raw_response = await backend.complete(
        model=identity.model,
        system_prompt=prompt_path.read_text(encoding="utf-8"),
        user_prompt=render_request(request),
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parse_judge_jsonl(raw_response, request=request, identity=identity)
