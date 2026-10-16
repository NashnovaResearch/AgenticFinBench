"""Private migration artifacts derived from the frozen v1 snapshot."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from fincarat.judges import EvidenceExcerpt
from fincarat.schema import AnswerSpan, FrozenModel
from fincarat.schema.common import Identifier, NonEmptyStr, Sha256

MIGRATED_CASE_SCHEMA_VERSION = "fincarat-migrated-v1-case-v1"
WEAK_SIGNAL_SCHEMA_VERSION = "fincarat-weak-signal-v1"


class Sensitivity(StrEnum):
    PRIVATE = "private"


class WeakSignalKind(StrEnum):
    JUDGE_FINDING = "v1_judge_finding"
    JUDGE_QUERY_VERDICT = "v1_judge_query_verdict"
    ENSEMBLE_FINDING = "v1_ensemble_finding"
    ENSEMBLE_QUERY_VERDICT = "v1_ensemble_query_verdict"
    GOLD_QUEUE = "gold_v1_queue"
    GOLD_MODEL = "gold_model_v1"


class LegacyAnswerUnit(FrozenModel):
    unit_id: Identifier
    text: NonEmptyStr
    span: AnswerSpan


class MigratedLegacyCase(FrozenModel):
    schema_version: Literal[MIGRATED_CASE_SCHEMA_VERSION] = MIGRATED_CASE_SCHEMA_VERSION
    query_id: Identifier
    prompt: NonEmptyStr
    answer: NonEmptyStr
    answer_sha256: Sha256
    as_of: AwareDatetime | None = None
    task_tags: dict[str, JsonValue] = Field(default_factory=dict)
    answer_units: tuple[LegacyAnswerUnit, ...]
    evidence: tuple[EvidenceExcerpt, ...]
    evidence_completeness: Literal["complete", "partial", "unavailable"]
    observability: NonEmptyStr
    origin_trace_id: str | None = None
    trace_snapshot_sha256: Sha256 | None = None
    source_bundle_sha256: Sha256
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    excluded_source_fields: tuple[NonEmptyStr, ...] = (
        "session_id",
        "provenance.session",
        "eval.ground_truth_targets",
    )
    migration_warnings: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def ids_and_spans_must_be_unique(self) -> MigratedLegacyCase:
        unit_ids = [unit.unit_id for unit in self.answer_units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("answer unit ids must be unique")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence ids must be unique")
        if self.evidence_completeness == "complete" and not self.evidence:
            raise ValueError("complete evidence requires at least one evidence item")
        if self.evidence_completeness == "unavailable" and self.evidence:
            raise ValueError("unavailable evidence cannot contain evidence items")
        return self


class WeakSignal(FrozenModel):
    schema_version: Literal[WEAK_SIGNAL_SCHEMA_VERSION] = WEAK_SIGNAL_SCHEMA_VERSION
    signal_id: Identifier
    query_id: Identifier
    kind: WeakSignalKind
    source_id: NonEmptyStr
    payload_sha256: Sha256
    payload: dict[str, JsonValue]
    intended_use: Literal["weak_supervision", "hard_sample_mining", "bias_analysis"]
    is_human_gold: Literal[False] = False


class MigrationArtifact(FrozenModel):
    path: NonEmptyStr
    sha256: Sha256
    records: int = Field(ge=0)


class MigrationManifest(FrozenModel):
    schema_version: Literal["fincarat-v1-migration-manifest-v1"] = (
        "fincarat-v1-migration-manifest-v1"
    )
    migration_id: Identifier
    source_release_sha256: Sha256
    source_release_schema_version: NonEmptyStr
    source_counts: dict[str, int]
    query_ids: tuple[Identifier, ...] = Field(min_length=1)
    policies: dict[str, JsonValue]
    inputs: tuple[MigrationArtifact, ...]
    outputs: tuple[MigrationArtifact, ...]
    warnings: tuple[NonEmptyStr, ...] = ()
