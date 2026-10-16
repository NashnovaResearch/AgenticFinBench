"""Financial Fact Card: the frozen truth contract for one benchmark task."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .common import (
    FinancialDateTime,
    FrozenModel,
    Identifier,
    NonEmptyStr,
    Sha256,
    TimeContext,
)

FACT_CARD_SCHEMA_VERSION = "fincarat-fact-card-v1"


class TaskType(StrEnum):
    TIME_SENSITIVE = "T1_time_sensitive"
    STATIC_LOOKUP = "T2_static_lookup"
    MULTI_STEP_INVESTIGATION = "T3_multi_step_investigation"


class Criticality(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class ComparatorKind(StrEnum):
    EXACT = "exact"
    ABSOLUTE_TOLERANCE = "absolute_tolerance"
    RELATIVE_TOLERANCE = "relative_tolerance"
    RANGE = "range"
    SET_MEMBERSHIP = "set_membership"
    SEMANTIC = "semantic"


class WorldBoundary(StrEnum):
    CLOSED = "closed_world"
    OPEN = "open_world"
    HYBRID = "hybrid"


class Comparator(FrozenModel):
    kind: ComparatorKind
    expected: JsonValue | None = None
    absolute_tolerance: Decimal | None = Field(default=None, ge=0)
    relative_tolerance: Decimal | None = Field(default=None, ge=0, le=1)
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None
    allowed_values: tuple[JsonValue, ...] = ()
    rubric: str | None = None

    @model_validator(mode="after")
    def validate_parameters(self) -> Comparator:
        if self.kind == ComparatorKind.ABSOLUTE_TOLERANCE:
            if self.expected is None or self.absolute_tolerance is None:
                raise ValueError("absolute_tolerance requires expected and absolute_tolerance")
        elif self.kind == ComparatorKind.RELATIVE_TOLERANCE:
            if self.expected is None or self.relative_tolerance is None:
                raise ValueError("relative_tolerance requires expected and relative_tolerance")
        elif self.kind == ComparatorKind.RANGE:
            if self.lower_bound is None or self.upper_bound is None:
                raise ValueError("range requires lower_bound and upper_bound")
            if self.lower_bound > self.upper_bound:
                raise ValueError("lower_bound must not exceed upper_bound")
        elif self.kind == ComparatorKind.SET_MEMBERSHIP and not self.allowed_values:
            raise ValueError("set_membership requires allowed_values")
        elif self.kind == ComparatorKind.SEMANTIC and not self.rubric:
            raise ValueError("semantic comparator requires rubric")
        elif self.kind == ComparatorKind.EXACT and self.expected is None:
            raise ValueError("exact comparator requires expected")
        return self


class SourceReference(FrozenModel):
    source_id: Identifier
    uri: NonEmptyStr
    publisher: NonEmptyStr
    title: str | None = None
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime
    content_sha256: Sha256 | None = None
    authority_tier: int = Field(ge=1, le=5)


class TruthFact(FrozenModel):
    fact_id: Identifier
    entity: NonEmptyStr
    metric_or_predicate: NonEmptyStr
    value: JsonValue
    unit: str | None = None
    currency: str | None = None
    financial_period: str | None = None
    as_of: FinancialDateTime | None = None
    provenance: tuple[SourceReference, ...] = Field(min_length=1)


class RequiredItem(FrozenModel):
    item_id: Identifier
    description: NonEmptyStr
    comparator: Comparator
    truth_fact_ids: tuple[Identifier, ...] = ()
    criticality: Criticality


class SourcePolicy(FrozenModel):
    authority_hierarchy: tuple[NonEmptyStr, ...] = Field(min_length=1)
    conflict_policy: NonEmptyStr
    revision_policy: NonEmptyStr


class DecisionBoundary(FrozenModel):
    world: WorldBoundary
    allowed_derivations: tuple[NonEmptyStr, ...] = ()
    abstention_conditions: tuple[NonEmptyStr, ...] = Field(min_length=1)


class TruthResolution(FrozenModel):
    anchor_snapshot_version: Identifier
    anchor_snapshot_sha256: Sha256
    claim_triggered_retrieval_policy: NonEmptyStr
    retrieval_cutoff: AwareDatetime


class FinancialFactCard(FrozenModel):
    schema_version: Literal[FACT_CARD_SCHEMA_VERSION] = FACT_CARD_SCHEMA_VERSION
    fact_card_version: Identifier
    query_id: Identifier
    task_type: TaskType
    benchmark_version: Identifier
    time: TimeContext
    required_items: tuple[RequiredItem, ...] = Field(min_length=1)
    truth_facts: tuple[TruthFact, ...] = Field(min_length=1)
    source_policy: SourcePolicy
    truth_resolution: TruthResolution
    decision_boundary: DecisionBoundary

    @model_validator(mode="after")
    def validate_references_and_uniqueness(self) -> FinancialFactCard:
        item_ids = [item.item_id for item in self.required_items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("required item ids must be unique")

        fact_ids = [fact.fact_id for fact in self.truth_facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("truth fact ids must be unique")

        known_facts = set(fact_ids)
        for item in self.required_items:
            unknown = set(item.truth_fact_ids) - known_facts
            if unknown:
                raise ValueError(
                    f"required item {item.item_id!r} references unknown truth facts: "
                    f"{sorted(unknown)}"
                )
        return self
