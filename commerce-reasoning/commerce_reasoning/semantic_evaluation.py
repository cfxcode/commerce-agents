"""Comparable semantic-context reports; construction failures are not model calls."""

from __future__ import annotations

from typing import Any

from .semantic_audit import aggregate_audits, audit_definitions, load_oracle
from .semantic_models import BUILDER_VERSION, content_hash
from .semantic_release import behavioral_config, semantic_identity, source_identity

COMPARISON_MANIFEST = {
    "schema_version": "1.0",
    "experiment": "semantic_context_closure",
    "variables": ["semantic_context_mode"],
    "generation": "llm",
    "max_token_ratio": 1.5,
    "primary_denominator": "all_submissions",
    "fixed": [
        "model",
        "guidance_model",
        "tools",
        "graph",
        "ontology",
        "schema",
        "source",
        "effective_prompts",
        "task_manifest",
        "environment",
        "effective_budgets",
        "checks",
    ],
}


def semantic_metrics(events: list[dict], *, oracle: dict | None = None) -> dict:
    built = [e for e in events if e["event_type"] == "semantic_context_built"]
    failed = [e for e in events if e["event_type"] == "semantic_context_failed"]
    starts = [e for e in events if e["event_type"] == "semantic_context_attempted"]
    # A constructed bundle can subsequently exceed the full-payload limit. Count that
    # as one failed attempt, not two attempts or a completed model request.
    attempts = {e["context_attempt_id"] for e in starts if e.get("context_attempt_id")}
    failures = {e["context_attempt_id"] for e in failed if e.get("context_attempt_id")}
    measured = [e for e in events if e["event_type"] == "guidance_input_measured"]
    attempt_count = len(attempts) if starts else len(built) + len(failed)
    failure_count = len(failures) if starts else len(failed)
    return {
        "builds": len(built),
        "failures": len(failed),
        "attempts": attempt_count,
        "failed_attempts": failure_count,
        "semantic_fallback_rate": failure_count / attempt_count if attempt_count else None,
        "attempt_accounting": "request_id" if starts else "legacy_event_approximation",
        "build_duration_ms": sum(e.get("duration_ms", 0) for e in built),
        "max_semantic_bytes": max((e.get("included_bytes", 0) for e in built), default=0),
        "max_guidance_input_bytes": max(
            (e.get("guidance_input_bytes", 0) for e in measured), default=0
        ),
        "guidance_input_measurements": len(measured),
        "guidance_budget_failures": sum(e.get("within_budget") is False for e in measured),
        "max_solver_request_bytes": max(
            (
                e.get("request_bytes", 0)
                for e in events
                if e["event_type"] == "solver_request_measured"
            ),
            default=0,
        ),
        "omitted_optional_refs": sum(len(e.get("omitted_optional_refs", [])) for e in built),
        "invalid_reference_count": sum(
            e.get("error_code") in {"SEMANTIC_REF_MISSING", "SEMANTIC_REF_KIND_MISMATCH"}
            for e in failed
        ),
        "failure_codes": sorted({e.get("error_code", "unknown") for e in failed}),
        "coverage": aggregate_audits([audit_definitions(e, oracle) for e in built]),
    }


def semantic_totals(rows: list[dict]) -> dict:
    summed = {
        key: sum(row.get(key, 0) for row in rows)
        for key in (
            "builds",
            "failures",
            "attempts",
            "failed_attempts",
            "build_duration_ms",
            "guidance_input_measurements",
            "guidance_budget_failures",
            "omitted_optional_refs",
            "invalid_reference_count",
        )
    }
    coverage = {
        key: sum(row.get("coverage", {}).get(key, 0) for row in rows)
        for key in (
            "required_expected",
            "required_present",
            "states_expected",
            "states_present",
            "irrelevant_definition_count",
            "measured_builds",
            "unmeasured_builds",
            "failed_audits",
        )
    }
    complete = coverage["measured_builds"] > 0 and coverage["unmeasured_builds"] == 0
    coverage.update(
        coverage_complete=complete,
        required_definition_coverage=coverage["required_present"] / coverage["required_expected"]
        if complete and coverage["required_expected"]
        else None,
        state_definition_coverage=coverage["states_present"] / coverage["states_expected"]
        if complete and coverage["states_expected"]
        else None,
    )
    return {
        **summed,
        "coverage": coverage,
        "semantic_fallback_rate": summed["failed_attempts"] / summed["attempts"]
        if summed["attempts"]
        else None,
        **{
            key: max((row.get(key, 0) for row in rows), default=0)
            for key in (
                "max_semantic_bytes",
                "max_guidance_input_bytes",
                "max_solver_request_bytes",
            )
        },
    }


def comparison_fields(root: Any, service: Any, agent_config: Any) -> dict:
    config = service.config
    mode = config.effective_semantic_mode
    fixed_config = behavioral_config(config)
    fixed_config.pop("semantic_context_mode")
    effective_budgets = {
        "pg_bytes": config.pg_budget_bytes
        if mode == "closure"
        else config.context_budget_tokens * 2,
        "guide_input_bytes": config.guidance_input_budget_bytes
        if mode == "closure"
        else config.context_budget_tokens * 3,
    }
    registry = service.registry.semantic_registry
    source = source_identity(root)
    prompts = service.effective_prompt_identity
    fixed = {
        "config": fixed_config,
        "agent_config": agent_config.model_dump(mode="json"),
        "model": agent_config.model,
        "guidance_model": config.guidance_model or agent_config.model,
        "graph_hash": service.graph.content_hash,
        "ontology_hash": service.registry.content_hash,
        "schema_hash": registry.schema_hash if registry else None,
        "source_hash": source["source_hash"],
        "effective_prompt_hash": prompts["combined_hash"],
        "effective_budgets": effective_budgets,
        "semantic_oracle_hash": content_hash(load_oracle(root)),
    }
    identity = None
    if registry:
        identity = semantic_identity(
            root,
            service.graph,
            service.loaded_config,
            guidance=service.guidance.system,
            solver=service.solver_notice,
        )
    return {
        "semantic_context_mode": mode,
        "graph_hash": service.graph.content_hash,
        "ontology_hash": service.registry.content_hash,
        "generation": "llm",
        "experiment_label": f"{config.effective_variant}_{mode}",
        "effective_config_hash": content_hash(
            {
                "reasoning": config.model_dump(mode="json"),
                "agent": agent_config.model_dump(mode="json"),
            }
        ),
        "fixed_factors_hash": content_hash(fixed),
        "fixed_factors": fixed,
        "comparison_manifest": COMPARISON_MANIFEST,
        "comparison_manifest_hash": content_hash(COMPARISON_MANIFEST),
        "builder_version": BUILDER_VERSION,
        "semantic_schema_hash": registry.schema_hash if registry else None,
        "effective_prompt_hash": prompts["combined_hash"],
        "runtime_source_hash": source["source_hash"],
        "semantic_identity": identity,
    }


def compare_semantic_reports(baseline: dict, candidate: dict) -> tuple[bool, list[str]]:
    reasons = []
    if (
        baseline.get("semantic_context_mode") != "legacy"
        or candidate.get("semantic_context_mode") != "closure"
    ):
        reasons.append("expected_legacy_vs_closure")
    if baseline.get("variant") != candidate.get("variant") or candidate.get("variant") not in {
        "T",
        "P",
        "E",
    }:
        reasons.append("incomparable_variant")
    for name in (
        "model",
        "manifest_hash",
        "environment_hash",
        "fixed_factors_hash",
        "comparison_manifest_hash",
        "graph_hash",
        "semantic_schema_hash",
        "runtime_source_hash",
        "effective_prompt_hash",
    ):
        if not baseline.get(name) or baseline[name] != candidate.get(name):
            reasons.append(f"incomparable_{name}")
    if baseline.get("generation") != "llm" or candidate.get("generation") != "llm":
        reasons.append("incomparable_generation")
    expected_manifest_hash = content_hash(COMPARISON_MANIFEST)
    for report in (baseline, candidate):
        if report.get("comparison_manifest_hash") != expected_manifest_hash:
            reasons.append("undeclared_comparison")
        for name in (
            "submitted",
            "valid",
            "successes",
            "total_tokens",
            "unmetered_calls",
            "safety_violations",
        ):
            if type(report.get(name)) is not int or report[name] < 0:
                reasons.append(f"invalid_{name}")
        if reasons and any(r.startswith("invalid_") for r in reasons):
            return False, sorted(set(reasons))
        if not report["submitted"] or report["valid"] != report["submitted"]:
            reasons.append("infrastructure_or_missing_evidence")
        if report["successes"] > report["valid"]:
            reasons.append("invalid_successes")
        if report["unmetered_calls"]:
            reasons.append("missing_usage_evidence")
        if report["safety_violations"]:
            reasons.append("safety_regression")
    if baseline.get("submitted") != candidate.get("submitted"):
        reasons.append("incomparable_submission_count")
    if candidate.get("successes", -1) < baseline.get("successes", 0):
        reasons.append("task_regression")
    old, new = baseline.get("critical_failures", {}), candidate.get("critical_failures", {})
    if not old or not new or old.keys() != new.keys():
        reasons.append("incomplete_critical_failures")
    else:
        for key in old:
            if (
                type(old[key]) is not int
                or type(new[key]) is not int
                or min(old[key], new[key]) < 0
            ):
                reasons.append("invalid_critical_failures")
            elif new[key] > old[key]:
                reasons.append(f"critical_regression:{key}")
    if (
        candidate.get("total_tokens", 0)
        > baseline.get("total_tokens", 0) * COMPARISON_MANIFEST["max_token_ratio"]
    ):
        reasons.append("cost_limit")
    return not reasons, sorted(set(reasons))
