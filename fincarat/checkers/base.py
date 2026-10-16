"""Shared result contract for deterministic checkers."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from fincarat.schema.common import FrozenModel, Identifier, NonEmptyStr

DETERMINISTIC_CHECKER_VERSION = "fincarat-deterministic-v1"


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT = "insufficient"
    NOT_APPLICABLE = "not_applicable"


class ComponentCheck(FrozenModel):
    component: NonEmptyStr
    status: CheckStatus
    code: Identifier
    observed: str | None = None
    expected: str | None = None
    detail: NonEmptyStr


class DeterministicAssessment(FrozenModel):
    checker_version: Identifier = DETERMINISTIC_CHECKER_VERSION
    claim_id: Identifier
    reference_fact_id: Identifier
    status: CheckStatus
    checks: tuple[ComponentCheck, ...] = Field(min_length=1)


def aggregate_status(checks: tuple[ComponentCheck, ...]) -> CheckStatus:
    applicable = [check.status for check in checks if check.status != CheckStatus.NOT_APPLICABLE]
    if CheckStatus.FAIL in applicable:
        return CheckStatus.FAIL
    if CheckStatus.INSUFFICIENT in applicable:
        return CheckStatus.INSUFFICIENT
    if applicable and all(status == CheckStatus.PASS for status in applicable):
        return CheckStatus.PASS
    return CheckStatus.NOT_APPLICABLE
