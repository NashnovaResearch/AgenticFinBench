"""Migrate the frozen v1 audit into private FinCARAT v2 input and weak-signal files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from fincarat.io import canonical_json_bytes, canonical_sha256, sha256_file, write_model
from fincarat.judges import EvidenceExcerpt
from fincarat.schema import AnswerSpan

from .schema import (
    LegacyAnswerUnit,
    MigratedLegacyCase,
    MigrationArtifact,
    MigrationManifest,
    WeakSignal,
    WeakSignalKind,
)


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            yield line_number, payload


def count_jsonl(path: Path) -> int:
    return sum(1 for _ in iter_jsonl(path))


def verify_release(source: Path, release: dict[str, Any]) -> tuple[MigrationArtifact, ...]:
    artifacts: list[MigrationArtifact] = []
    for relative, expected in release["files"].items():
        path = source / relative
        _reject_lfs_pointer(path)
        actual_sha = sha256_file(path)
        if actual_sha != expected["sha256"]:
            raise ValueError(f"sha256 mismatch for {relative}: {actual_sha}")
        records = count_jsonl(path) if path.suffix == ".jsonl" else 0
        if expected.get("records") is not None and records != expected["records"]:
            raise ValueError(
                f"record count mismatch for {relative}: {records} != {expected['records']}"
            )
        artifacts.append(
            MigrationArtifact(path=relative, sha256=actual_sha, records=records)
        )
    return tuple(artifacts)


def migrate(
    *,
    source: Path,
    output: Path,
    gold_queue: Path | None = None,
    gold_model: Path | None = None,
) -> MigrationManifest:
    release_path = source / "RELEASE.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    inputs = verify_release(source, release)

    bundle_path = source / "bundles.jsonl"
    cases_path = output / "cases.v1.jsonl"
    case_query_ids: list[str] = []

    def cases() -> Iterator[dict[str, Any]]:
        for _, bundle in iter_jsonl(bundle_path):
            migrated = migrate_bundle(bundle)
            case_query_ids.append(migrated.query_id)
            yield migrated.model_dump(mode="json")

    case_records = write_jsonl(cases_path, cases())

    signals_path = output / "weak-signals.v1.jsonl"
    signal_query_ids: set[str] = set()
    warnings: list[str] = []

    def signals() -> Iterator[dict[str, Any]]:
        for row in _judge_signals(source):
            signal_query_ids.add(row.query_id)
            yield row.model_dump(mode="json")
        for row in _ensemble_signals(source):
            signal_query_ids.add(row.query_id)
            yield row.model_dump(mode="json")
        for optional_path, kind in (
            (gold_queue, WeakSignalKind.GOLD_QUEUE),
            (gold_model, WeakSignalKind.GOLD_MODEL),
        ):
            if optional_path is None or not optional_path.exists():
                warnings.append(f"{kind.value} was not available during migration")
                continue
            for row in _gold_signals(optional_path, kind):
                signal_query_ids.add(row.query_id)
                yield row.model_dump(mode="json")

    signal_records = write_jsonl(signals_path, signals())

    expected_queries = set(case_query_ids)
    if len(case_query_ids) != len(expected_queries):
        raise ValueError("bundle query ids are not unique")
    if not signal_query_ids.issubset(expected_queries):
        extra = sorted(signal_query_ids - expected_queries)
        raise ValueError(f"weak signals contain queries without bundles: {extra}")

    outputs = (
        MigrationArtifact(
            path=str(cases_path),
            sha256=sha256_file(cases_path),
            records=case_records,
        ),
        MigrationArtifact(
            path=str(signals_path),
            sha256=sha256_file(signals_path),
            records=signal_records,
        ),
    )
    counts = release["counts"]
    manifest = MigrationManifest(
        migration_id="origin-trace-smoke-v1-to-fincarat-v2",
        source_release_sha256=sha256_file(release_path),
        source_release_schema_version=release["schema_version"],
        source_counts={
            "bundles": counts["bundles_n"],
            "origin_traces": counts["origin_traces_n"],
            "ensemble": counts["ensemble_n"],
            "judges": len(tuple((source / "judges").glob("*.jsonl"))),
            "migrated_cases": case_records,
            "weak_signals": signal_records,
        },
        query_ids=tuple(case_query_ids),
        policies={
            "source_mode": "read_only",
            "sensitivity": "private",
            "exclude_eval_ground_truth_from_judge_input": True,
            "legacy_labels_are_human_gold": False,
            "claim_slate_requires_fresh_extraction": True,
            "idempotency_key": "source_release_sha256",
        },
        inputs=inputs,
        outputs=outputs,
        warnings=tuple(warnings),
    )
    write_model(output / "migration-manifest.v1.json", manifest)
    return manifest


def migrate_bundle(bundle: dict[str, Any]) -> MigratedLegacyCase:
    answer = str(bundle["answer"])
    answer_units = tuple(
        LegacyAnswerUnit(
            unit_id=unit["id"],
            text=unit["text"],
            span=AnswerSpan(
                unit_id=unit["id"],
                start=unit["start"],
                end=unit["end"],
            ),
        )
        for unit in bundle.get("answer_units", ())
    )
    evidence = tuple(_migrate_evidence(item) for item in bundle.get("evidence_items", ()))
    warnings = list(bundle.get("trace_completeness_reasons", ()))
    if bundle.get("evidence_truncated"):
        warnings.append("v1 evidence text was truncated")
    if not evidence:
        completeness = "unavailable"
    elif bundle.get("evidence_truncated") or not bundle.get("trace_complete", False):
        completeness = "partial"
    else:
        completeness = "complete"
    return MigratedLegacyCase(
        query_id=bundle["query_id"],
        prompt=bundle["prompt"],
        answer=answer,
        answer_sha256=hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        as_of=bundle.get("as_of"),
        task_tags=bundle.get("tags", {}),
        answer_units=answer_units,
        evidence=evidence,
        evidence_completeness=completeness,
        observability=bundle.get("observability", "unknown"),
        origin_trace_id=bundle.get("origin_trace_id"),
        trace_snapshot_sha256=bundle.get("trace_snapshot_sha256"),
        source_bundle_sha256=canonical_sha256(bundle),
        migration_warnings=tuple(dict.fromkeys(warnings)),
    )


def _migrate_evidence(item: dict[str, Any]) -> EvidenceExcerpt:
    raw_input = item.get("input")
    raw_output = item.get("output")
    rendered_input = _render_json_value(raw_input)
    rendered_output = _render_json_value(raw_output)
    name = str(item.get("name") or item.get("source") or "tool")
    return EvidenceExcerpt(
        evidence_id=item["evidence_id"],
        source_type=name,
        text=f"Tool: {name}\nInput: {rendered_input}\nOutput: {rendered_output}",
        observed_at=item.get("startTime"),
        call_id=item.get("call_id"),
        input_sha256=hashlib.sha256(canonical_json_bytes(raw_input)).hexdigest(),
        output_sha256=hashlib.sha256(canonical_json_bytes(raw_output)).hexdigest(),
    )


def _judge_signals(source: Path) -> Iterator[WeakSignal]:
    for path in sorted((source / "judges").glob("*.jsonl")):
        source_id = path.stem
        for _, row in iter_jsonl(path):
            query_id = row["query_id"]
            query_payload = {
                "verdict": row.get("verdict"),
                "evidence_sufficient": row.get("evidence_sufficient"),
                "confidence": row.get("confidence"),
                "requested_judge_model": row.get("requested_judge_model"),
                "returned_judge_model": row.get("returned_judge_model"),
                "judge_family": row.get("judge_family"),
                "validation_errors": row.get("validation_errors", []),
            }
            yield _weak_signal(
                query_id,
                WeakSignalKind.JUDGE_QUERY_VERDICT,
                source_id,
                query_payload,
                index=0,
            )
            for index, finding in enumerate(row.get("findings", ()), start=1):
                yield _weak_signal(
                    query_id,
                    WeakSignalKind.JUDGE_FINDING,
                    source_id,
                    finding,
                    index=index,
                )


def _ensemble_signals(source: Path) -> Iterator[WeakSignal]:
    path = source / "merged" / "ensemble-smoke-v1.jsonl"
    for _, row in iter_jsonl(path):
        query_id = row["query_id"]
        yield _weak_signal(
            query_id,
            WeakSignalKind.ENSEMBLE_QUERY_VERDICT,
            "ensemble-smoke-v1",
            {
                "ensemble_verdict": row.get("ensemble_verdict"),
                "valid_judge_count": row.get("valid_judge_count"),
                "expected_judge_count": row.get("expected_judge_count"),
                "judge_verdicts": row.get("judge_verdicts", {}),
                "evidence_sufficient_votes": row.get("evidence_sufficient_votes"),
            },
            index=0,
        )
        index = 0
        for group in ("confirmed_findings", "possible_findings", "suspect_findings"):
            for finding in row.get(group, ()):
                index += 1
                payload = {"v1_group": group, **finding}
                yield _weak_signal(
                    query_id,
                    WeakSignalKind.ENSEMBLE_FINDING,
                    "ensemble-smoke-v1",
                    payload,
                    index=index,
                )


def _gold_signals(path: Path, kind: WeakSignalKind) -> Iterator[WeakSignal]:
    for index, row in iter_jsonl(path):
        query_id = row.get("query_id")
        if not query_id:
            item_id = str(row.get("item_id", ""))
            query_id = item_id[:9] if item_id.startswith("core-") else None
        if not query_id:
            raise ValueError(f"{path}:{index}: gold row has no query_id")
        payload = {
            key: value
            for key, value in row.items()
            if key not in {"answer", "evidence_cards", "before", "after"}
        }
        yield _weak_signal(query_id, kind, path.name, payload, index=index)


def _weak_signal(
    query_id: str,
    kind: WeakSignalKind,
    source_id: str,
    payload: dict[str, Any],
    *,
    index: int,
) -> WeakSignal:
    payload_sha256 = canonical_sha256(payload)
    signal_digest = hashlib.sha256(
        f"{kind.value}:{query_id}:{source_id}:{index}:{payload_sha256}".encode()
    ).hexdigest()[:16]
    return WeakSignal(
        signal_id=f"{query_id}:{signal_digest}",
        query_id=query_id,
        kind=kind,
        source_id=source_id,
        payload_sha256=payload_sha256,
        payload=payload,
        intended_use=(
            "hard_sample_mining"
            if kind in {WeakSignalKind.ENSEMBLE_FINDING, WeakSignalKind.GOLD_QUEUE}
            else "weak_supervision"
        ),
    )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    count = 0
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return count


def _render_json_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def _reject_lfs_pointer(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("rb") as handle:
        prefix = handle.read(64)
    if prefix.startswith(b"version https://git-lfs.github.com/spec"):
        raise ValueError(f"{path} is a Git LFS pointer; run git lfs pull first")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--gold-queue", type=Path)
    parser.add_argument("--gold-model", type=Path)
    args = parser.parse_args()
    manifest = migrate(
        source=args.source.resolve(),
        output=args.out.resolve(),
        gold_queue=args.gold_queue.resolve() if args.gold_queue else None,
        gold_model=args.gold_model.resolve() if args.gold_model else None,
    )
    print(
        json.dumps(
            {
                "migration_id": manifest.migration_id,
                "cases": manifest.source_counts["migrated_cases"],
                "weak_signals": manifest.source_counts["weak_signals"],
                "warnings": manifest.warnings,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
