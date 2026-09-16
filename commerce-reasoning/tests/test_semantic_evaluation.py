"""Offline report contracts and preflight; no real-model accuracy is asserted."""

import copy
import json
from pathlib import Path

import pytest

from commerce_reasoning.config import ReasoningConfig
from commerce_reasoning.evaluation import make_environment, metrics
from commerce_reasoning.procedural import load_knowledge
from commerce_reasoning.semantic_cli import inspect, preflight
from commerce_reasoning.semantic_evaluation import compare_semantic_reports, comparison_fields

ROOT = Path(__file__).resolve().parents[2]


async def pair():
    reports = []
    case = json.loads((ROOT / "evals/commerce_reasoning/tasks/T01.json").read_text())
    for mode in ("legacy", "closure"):
        config = ReasoningConfig.from_file(ROOT / f"configs/experiments/p-{mode}.yaml")
        env = await make_environment(ROOT, case, "P", reasoning_config=config)
        try:
            reports.append(
                {
                    **comparison_fields(ROOT, env.service, env.config),
                    "variant": "P",
                    "model": env.config.model,
                    "manifest_hash": "synthetic",
                    "environment_hash": "synthetic",
                    "submitted": 3,
                    "valid": 3,
                    "successes": 3,
                    "total_tokens": 100,
                    "unmetered_calls": 0,
                    "safety_violations": 0,
                    "critical_failures": {"stock": 0, "host_authorization": 0},
                }
            )
        finally:
            env.service.store.close()
    return reports


async def test_paired_configs_hold_all_factors_except_semantic_mode_fixed():
    baseline, candidate = await pair()
    assert baseline["effective_config_hash"] != candidate["effective_config_hash"]
    assert baseline["fixed_factors_hash"] == candidate["fixed_factors_hash"]
    assert (
        baseline["experiment_label"] == "P_legacy" and candidate["experiment_label"] == "P_closure"
    )
    assert compare_semantic_reports(baseline, candidate) == (True, [])


@pytest.mark.parametrize(
    "field,value",
    [
        ("fixed_factors_hash", "different"),
        ("model", "other-model"),
        ("generation", "render"),
        ("semantic_schema_hash", "different"),
        ("runtime_source_hash", "different"),
        ("effective_prompt_hash", "different"),
        ("unmetered_calls", 1),
        ("successes", 2),
        ("valid", 2),
        ("total_tokens", 151),
        ("safety_violations", 1),
        ("comparison_manifest_hash", "undeclared"),
        ("submitted", 0),
        ("successes", -1),
    ],
)
async def test_incomparable_or_regressed_evidence_is_rejected(field, value):
    baseline, candidate = await pair()
    changed = copy.deepcopy(candidate)
    changed[field] = value
    assert compare_semantic_reports(baseline, changed)[0] is False


def test_construction_failures_and_unknown_usage_are_counted_separately():
    events = [
        {
            "event_type": "semantic_context_failed",
            "role": "semantic",
            "model_requested": False,
            "error_code": "SEMANTIC_BUDGET_EXCEEDED",
        },
        {
            "event_type": "guidance_failed",
            "role": "guidance",
            "model_requested": True,
            "usage_known": False,
        },
        {
            "event_type": "guidance_generated",
            "role": "guidance",
            "model_requested": True,
            "input_tokens": 10,
            "output_tokens": 2,
        },
    ]
    result = metrics(events)
    assert result["usage"]["guidance"]["calls"] == 2
    assert result["usage"]["guidance"]["input_tokens"] == 10
    assert result["unmetered_calls"] == 1
    assert result["semantic"]["failures"] == 1


def test_real_retriever_preflight_covers_every_node_and_zero_hops():
    config = ReasoningConfig.from_file(ROOT / "configs/experiments/p-closure.yaml")
    registry, graph = load_knowledge(ROOT, config)
    report = preflight(config, registry, graph)
    assert report["passed"] and report["cases"] == 135
    assert report["no_model_calls"] and report["no_business_writes"]
    assert not any(row["omitted_pg_edges"] for row in report["results"])
    result = inspect(
        ROOT,
        config,
        registry,
        graph,
        ROOT / "commerce-reasoning/tests/fixtures/semantic_context/waiting.json",
        "WAIT_APPROVAL",
        0,
    )
    assert not result["public"]["actions"]
    assert {row["id"] for row in result["public"]["states"]} == {"waiting_for_host"}
