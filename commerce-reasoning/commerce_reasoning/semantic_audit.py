"""Independent specification oracles for definition coverage, never runtime permission."""

from __future__ import annotations

import json
from pathlib import Path

from .semantic_models import content_hash

ORACLE_PATH = "evals/commerce_reasoning/semantic/definition-oracle.v1.json"


def load_oracle(root: Path) -> dict:
    definition = json.loads((root / ORACLE_PATH).read_text())
    if definition.get("schema_version") != "1.0" or not definition.get("seeds"):
        raise ValueError("Invalid semantic coverage oracle")
    for seed, row in definition["seeds"].items():
        if not isinstance(seed, str) or ":" not in seed or set(row) != {"required", "optional"}:
            raise ValueError("Invalid semantic coverage seed")
        for field in ("required", "optional"):
            if not isinstance(row[field], list) or any(
                not isinstance(x, str) or ":" not in x for x in row[field]
            ):
                raise ValueError("Invalid expected definition list")
            if len(row[field]) != len(set(row[field])):
                raise ValueError("Duplicate expected definition")
    return definition


def audit_definitions(event: dict, oracle: dict | None) -> dict:
    """Only sets authored separately from the builder count as expected coverage."""
    state_seeds = {"states:" + name for name in event.get("seed_state_refs", [])}
    seeds = (
        {"actions:" + name for name in event.get("seed_action_refs", [])}
        | state_seeds
        | {"entities:" + name for name in event.get("observed_type_ids", [])}
    )
    available = event.get("included_definition_refs")
    missing_oracle = sorted(seeds - oracle["seeds"].keys()) if oracle else sorted(seeds)
    if oracle is None or available is None or missing_oracle:
        return {
            "status": "unmeasured",
            "reason": "oracle_or_definition_evidence_missing",
            "uncovered_seeds": missing_oracle,
        }
    required: set[str] = set()
    allowed: set[str] = set()
    for seed in sorted(seeds):
        row = oracle["seeds"][seed]
        required.update(row["required"])
        allowed.update(row["required"])
        allowed.update(row["optional"])
    actual = set(available)
    missing = sorted(required - actual)
    irrelevant = sorted(actual - allowed)
    return {
        "status": "measured",
        "oracle_hash": content_hash(oracle),
        "required_expected": len(required),
        "required_present": len(required & actual),
        "required_definition_coverage": len(required & actual) / len(required)
        if required
        else None,
        "states_expected": len(state_seeds),
        "states_present": len(state_seeds & actual),
        "state_definition_coverage": len(state_seeds & actual) / len(state_seeds)
        if state_seeds
        else None,
        "missing_required_refs": missing,
        "irrelevant_definition_count": len(irrelevant),
        "irrelevant_refs": irrelevant,
        "passed": not missing and not irrelevant,
    }


def aggregate_audits(audits: list[dict]) -> dict:
    measured = [row for row in audits if row["status"] == "measured"]
    counts = {
        key: sum(row[key] for row in measured)
        for key in (
            "required_expected",
            "required_present",
            "states_expected",
            "states_present",
            "irrelevant_definition_count",
        )
    }
    complete = len(measured) == len(audits) and bool(audits)
    return {
        **counts,
        "measured_builds": len(measured),
        "unmeasured_builds": len(audits) - len(measured),
        "coverage_complete": complete,
        "required_definition_coverage": counts["required_present"] / counts["required_expected"]
        if complete and counts["required_expected"]
        else None,
        "state_definition_coverage": counts["states_present"] / counts["states_expected"]
        if complete and counts["states_expected"]
        else None,
        "oracle_hashes": sorted({row["oracle_hash"] for row in measured}),
        "failed_audits": sum(not row["passed"] for row in measured),
    }
