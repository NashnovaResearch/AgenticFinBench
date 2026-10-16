"""Reproducibility manifest for FinCARAT development, pilot, and formal runs."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .common import (
    FileDigest,
    FrozenModel,
    Identifier,
    NonEmptyStr,
    Probability,
    RepositoryRevision,
    Sha256,
    TimeContext,
)

RUN_MANIFEST_SCHEMA_VERSION = "fincarat-run-manifest-v1"
SOURCE_LOCK_SCHEMA_VERSION = "fincarat-source-lock-v1"


class RunKind(StrEnum):
    DEVELOPMENT = "development"
    PILOT = "pilot"
    FORMAL = "formal"


class CalibrationStatus(StrEnum):
    UNCALIBRATED = "uncalibrated"
    HUMAN_ANCHORED = "human_anchored"


class BenchmarkLock(FrozenModel):
    repository: RepositoryRevision
    version: Identifier
    query_ids: tuple[Identifier, ...] = Field(min_length=1)
    query_file: FileDigest
    split: NonEmptyStr
    split_seed: int

    @model_validator(mode="after")
    def query_ids_must_be_unique(self) -> BenchmarkLock:
        if len(self.query_ids) != len(set(self.query_ids)):
            raise ValueError("benchmark query_ids must be unique")
        return self


class TruthSnapshotLock(FrozenModel):
    version: Identifier
    manifest: FileDigest
    retrieval_policy_sha256: Sha256


class ModelDeployment(FrozenModel):
    provider: NonEmptyStr
    model: NonEmptyStr
    deployment_version: NonEmptyStr


class AgentConfiguration(FrozenModel):
    model: ModelDeployment
    prompt_sha256: Sha256
    parameters: dict[str, JsonValue]
    tool_policy_version: Identifier


class ExtractorConfiguration(FrozenModel):
    primary: ModelDeployment
    reviewer: ModelDeployment | None = None
    prompt_sha256: Sha256
    temperature: float = Field(ge=0)
    max_tokens: int = Field(gt=0)


class JudgeConfiguration(FrozenModel):
    judge_id: Identifier
    role: NonEmptyStr
    model: ModelDeployment
    prompt_sha256: Sha256
    temperature: float = Field(ge=0)
    max_tokens: int = Field(gt=0)
    same_family_as_evaluated_model: bool


class DeterministicCheckerLock(FrozenModel):
    version: Identifier
    source_sha256: Sha256
    rule_manifest_sha256: Sha256


class CalibrationLock(FrozenModel):
    status: CalibrationStatus
    version: Identifier | None = None
    artifact_sha256: Sha256 | None = None
    coefficients: dict[str, float] = Field(default_factory=dict)
    human_gold_version: Identifier | None = None

    @model_validator(mode="after")
    def calibrated_runs_require_frozen_artifacts(self) -> CalibrationLock:
        if self.status == CalibrationStatus.HUMAN_ANCHORED:
            missing = [
                name
                for name in ("version", "artifact_sha256", "human_gold_version")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(
                    f"human-anchored calibration requires fields: {', '.join(missing)}"
                )
        return self


class DecisionThresholds(FrozenModel):
    tau_low: Probability
    tau_high: Probability
    c_min: Probability
    selection_basis: NonEmptyStr

    @model_validator(mode="after")
    def thresholds_must_be_ordered(self) -> DecisionThresholds:
        if self.tau_low >= self.tau_high:
            raise ValueError("tau_low must be lower than tau_high")
        return self


class RetryPolicy(FrozenModel):
    max_attempts: int = Field(ge=1)
    retryable_failures: tuple[NonEmptyStr, ...]
    backoff_policy: NonEmptyStr
    rerun_policy: NonEmptyStr


class ExecutionEnvironment(FrozenModel):
    environment_id: NonEmptyStr
    operating_system: NonEmptyStr
    python_version: NonEmptyStr
    dependency_lock: FileDigest
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    retry_policy: RetryPolicy

    @model_validator(mode="after")
    def run_window_must_be_ordered(self) -> ExecutionEnvironment:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not be earlier than started_at")
        return self


class LegacySourceLock(FrozenModel):
    source_id: Identifier
    source_kind: NonEmptyStr
    version: Identifier
    artifact: FileDigest
    intended_use: NonEmptyStr
    is_human_gold: bool = False


class SourceLockManifest(FrozenModel):
    """Phase-0 lock before any pilot data is transformed."""

    schema_version: Literal[SOURCE_LOCK_SCHEMA_VERSION] = SOURCE_LOCK_SCHEMA_VERSION
    created_at: AwareDatetime
    protocol_version: Identifier
    implementation_repository: RepositoryRevision
    benchmark_repository: RepositoryRevision
    implementation_root: NonEmptyStr
    state_root: NonEmptyStr
    source_data_mode: Literal["read_only"] = "read_only"
    notes: tuple[NonEmptyStr, ...] = ()


class RunManifest(FrozenModel):
    schema_version: Literal[RUN_MANIFEST_SCHEMA_VERSION] = RUN_MANIFEST_SCHEMA_VERSION
    protocol_version: Identifier
    run_id: Identifier
    run_kind: RunKind
    time: TimeContext
    benchmark: BenchmarkLock
    truth_snapshot: TruthSnapshotLock
    harness: RepositoryRevision
    agent: AgentConfiguration
    repetitions: int = Field(ge=1)
    extractor: ExtractorConfiguration
    judges: tuple[JudgeConfiguration, ...] = Field(min_length=1)
    deterministic_checker: DeterministicCheckerLock
    calibration: CalibrationLock
    thresholds: DecisionThresholds
    execution: ExecutionEnvironment
    schema_artifacts: tuple[FileDigest, ...] = Field(min_length=1)
    legacy_sources: tuple[LegacySourceLock, ...] = ()

    @model_validator(mode="after")
    def validate_run_contract(self) -> RunManifest:
        judge_ids = [judge.judge_id for judge in self.judges]
        if len(judge_ids) != len(set(judge_ids)):
            raise ValueError("judge ids must be unique")
        if self.run_kind == RunKind.FORMAL:
            if self.calibration.status != CalibrationStatus.HUMAN_ANCHORED:
                raise ValueError("formal runs require human-anchored calibration")
            if self.harness.dirty or self.benchmark.repository.dirty:
                raise ValueError("formal runs require clean harness and benchmark revisions")
        mislabeled_gold = [
            source.source_id for source in self.legacy_sources if source.is_human_gold
        ]
        if mislabeled_gold:
            raise ValueError(
                "legacy sources cannot be declared human gold; "
                "use human_gold_version in calibration: "
                f"{mislabeled_gold}"
            )
        return self
