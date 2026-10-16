"""Pure source validation, merging and scoring. No networking or filesystem writes."""

import copy
import hashlib
import json
import math
from collections import Counter

VERSION = "audit-quality-q-v1-draft"
IDENTITY = (
    "config_id",
    "answer_key",
    "source_run",
    "question_sha256",
    "answer_sha256",
    "claims_sha256",
    "rubric_sha256",
    "judgment_sha256",
    "audit_result_sha256",
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )


def require(ok, message):
    if not ok:
        raise ValueError(message)


def outcome(item):
    if item is None:
        return "missing"
    t, f = item.get("trace_verdict"), item.get("factual_verdict")
    if t not in ("supported", "unsupported", "incomplete") or f not in (
        "supported",
        "contradicted",
        "unresolved",
    ):
        return "missing"
    if t == "supported":
        return "grounded"
    return {
        "supported": "verified_ungrounded",
        "contradicted": "hallucinated",
        "unresolved": "unverified",
    }[f]


def verdicts(items):
    require(len({x["id"] for x in items}) == len(items), "duplicate judgment ID")
    require(all(type(x.get("verdict")) is bool for x in items), "nonbinary verdict")
    return {x["id"]: x["verdict"] for x in items}


def validate_rubric(r):
    ps = {x["id"]: x for x in r["positive"]}
    ns = {x["id"]: x for x in r["negative"]}
    require(len(ps) == len(r["positive"]) and len(ns) == len(r["negative"]), "duplicate rule ID")
    require(
        all(math.isfinite(x["weight"]) and x["weight"] >= 0 for x in ps.values()), "invalid weight"
    )
    require(abs(math.fsum(x["weight"] for x in ps.values()) - 100) <= 1e-8, "budget not 100")
    owner = {}
    for n in ns.values():
        require(math.isfinite(n["penalty_points"]) and n["penalty_points"] >= 0, "invalid penalty")
        require(
            n["score_cap"] is None or math.isfinite(n["score_cap"]) and 0 <= n["score_cap"] <= 100,
            "invalid cap",
        )
        require(bool(n["dedup_group"]), "missing root")
        for k in ("overlap_positive_ids", "invalidates_positive_ids"):
            require(
                len(set(n[k])) == len(n[k]) and set(n[k]) <= ps.keys(), "invalid positive links"
            )
        for pid in n["overlap_positive_ids"]:
            require(
                pid not in owner or owner[pid] == n["dedup_group"],
                "cross-group credit conflict: " + pid,
            )
            owner[pid] = n["dedup_group"]
    if r.get("dimensions"):
        ids = [p for d in r["dimensions"] for p in d["positive_ids"]]
        require(len(set(ids)) == len(ids) and set(ids) == ps.keys(), "dimension partition")


def score(j, r):
    validate_rubric(r)
    p = verdicts(j["positive"])
    n = verdicts(j["negative"])
    require(
        set(p) == {x["id"] for x in r["positive"]} and set(n) == {x["id"] for x in r["negative"]},
        "judgment IDs mismatch",
    )
    w = {x["id"]: x["weight"] for x in r["positive"]}
    groups = {}
    caps = []
    for rule in r["negative"]:
        if not n[rule["id"]]:
            continue
        require(
            not any(p[k] for k in rule["invalidates_positive_ids"]),
            "trigger contradicts invalidated positive",
        )
        g = groups.setdefault(
            rule["dedup_group"],
            {"triggered_ids": [], "nominal_penalty": 0, "overlap_ids": set(), "cap": 100},
        )
        g["triggered_ids"].append(rule["id"])
        g["nominal_penalty"] = max(g["nominal_penalty"], rule["penalty_points"])
        g["overlap_ids"].update(rule["overlap_positive_ids"])
        if rule["score_cap"] is not None:
            caps.append({"id": rule["id"], "score_cap": rule["score_cap"]})
            g["cap"] = min(g["cap"], rule["score_cap"])
    for g in groups.values():
        g["overlap_ids"] = sorted(g["overlap_ids"])
        g["positive_loss_credit"] = math.fsum(w[k] for k in g["overlap_ids"] if not p[k])
        g["effective_penalty"] = max(0, g["nominal_penalty"] - g["positive_loss_credit"])
    base = math.fsum(w[k] for k in p if p[k])
    penalty = math.fsum(g["effective_penalty"] for g in groups.values())
    before = max(0, base - penalty)
    cap = min([100] + [x["score_cap"] for x in caps])
    q = min(before, cap)
    dims = {
        d["name"]: {
            "budget": d["budget"],
            "earned": math.fsum(w[k] for k in d["positive_ids"] if p[k]),
        }
        for d in r.get("dimensions", [])
    }
    require(
        not dims or abs(math.fsum(d["earned"] for d in dims.values()) - base) <= 1e-8,
        "dimension sum mismatch",
    )
    return {
        "base_score": base,
        "penalty": penalty,
        "score_before_cap": before,
        "score_cap": cap,
        "cap_applied": before - q > 1e-8,
        "cap_reduction": before - q,
        "score": q,
        "penalty_groups": groups,
        "cap_candidates": caps,
        "dimension_scores": dims,
    }

