"""Frozen atomic claim slate shared by every verifier and judge."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .common import FinancialDateTime, FrozenModel, Identifier, NonEmptyStr, Sha256

CLAIM_SLATE_SCHEMA_VERSION = "fincarat-claim-slate-v1"


class ClaimType(StrEnum):
    NUMERIC_FACT = "numeric_fact"
    DERIVED_NUMERIC = "derived_numeric"
    EVENT_FACT = "event_fact"
    SOURCE_ATTRIBUTION = "source_attribution"
    MECHANISM_STATEMENT = "mechanism_statement"
    JUDGMENT_OR_PREDICTION = "judgment_or_prediction"


class Verifiability(StrEnum):
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"
    NOT_VERIFIABLE = "not_verifiable"


class Subject(FrozenModel):
    name: NonEmptyStr
    ticker: str | None = None
    market: str | None = None
    entity_id: str | None = None


class AnswerSpan(FrozenModel):
    unit_id: Identifier
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def end_must_follow_start(self) -> AnswerSpan:
        if self.end <= self.start:
            raise ValueError("answer span end must be greater than start")
        return self


class ExtractorRecord(FrozenModel):
    model: NonEmptyStr
    deployment: str | None = None
    prompt_sha256: Sha256
    reviewer_model: NonEmptyStr | None = None
    reviewer_deployment: str | None = None


class AtomicClaim(FrozenModel):
    claim_id: Identifier
    claim_text: NonEmptyStr
    claim_type: ClaimType
    subject: Subject | None = None
    predicate_or_metric: str | None = None
    value: JsonValue | None = None
    unit: str | None = None
    currency: str | None = None
    financial_period: str | None = None
    as_of: FinancialDateTime | None = None
    source_attribution: str | None = None
    answer_span: AnswerSpan
    is_key_claim: bool
    verifiability: Verifiability
    enters_factual_denominator: bool

    @model_validator(mode="after")
    def validate_claim_routing(self) -> AtomicClaim:
        is_prediction = self.claim_type == ClaimType.JUDGMENT_OR_PREDICTION
        if is_prediction and self.enters_factual_denominator:
            raise ValueError("judgments and predictions do not enter the factual denominator")
        if is_prediction and self.verifiability != Verifiability.NOT_VERIFIABLE:
            raise ValueError("judgments and predictions must use not_verifiable routing")
        if not is_prediction and not self.enters_factual_denominator:
            raise ValueError("factual claim types must enter the factual denominator")
        if self.claim_type in {ClaimType.NUMERIC_FACT, ClaimType.DERIVED_NUMERIC}:
            missing = [
                field
                for field in ("subject", "predicate_or_metric", "value")
                if getattr(self, field) is None
            ]
            if missing:
                raise ValueError(f"numeric claims require structured fields: {', '.join(missing)}")
        return self


class ClaimSlate(FrozenModel):
    schema_version: Literal[CLAIM_SLATE_SCHEMA_VERSION] = CLAIM_SLATE_SCHEMA_VERSION
    claim_slate_version: Identifier
    query_id: Identifier
    created_at: AwareDatetime
    extractor: ExtractorRecord
    answer_sha256: Sha256
    claims: tuple[AtomicClaim, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def claim_ids_must_be_unique_and_scoped(self) -> ClaimSlate:
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim ids must be unique")
        prefix = f"{self.query_id}-c"
        out_of_scope = [claim_id for claim_id in claim_ids if not claim_id.startswith(prefix)]
        if out_of_scope:
            raise ValueError(f"claim ids must start with {prefix!r}: {out_of_scope}")
        return self
