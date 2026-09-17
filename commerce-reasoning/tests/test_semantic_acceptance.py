"""Acceptance gaps: independent coverage, wire payload budgets and lifecycle isolation."""

import copy
import json
from pathlib import Path

import pytest

from commerce_common.testing import FakeCreateClient, text_message
from commerce_reasoning.config import ReasoningConfig
from commerce_reasoning.evaluation import make_environment, metrics
from commerce_reasoning.procedural import load_knowledge
from commerce_reasoning.semantic_audit import aggregate_audits, audit_definitions, load_oracle
from commerce_reasoning.semantic_evaluation import semantic_metrics, semantic_totals
from commerce_reasoning.semantic_preflight import full_payload_preflight
from commerce_reasoning.semantic_runtime import guidance_budget

ROOT = Path(__file__).resolve().parents[2]


def config(**updates):
    return ReasoningConfig.from_file(ROOT / "configs/experiments/p-closure.yaml").model_copy(
        update=updates
    )


def case():
    return json.loads((ROOT / "evals/commerce_reasoning/tasks/T01.json").read_text())


def guide():
    return FakeCreateClient(
        [text_message('{"immediate_goal":"Wait for the host.","recommended_action_refs":[]}')] * 10
    )


def test_independent_oracle_detects_missing_and_irrelevant_definitions():
    oracle = load_oracle(ROOT)
    expected = oracle["seeds"]["states:waiting_for_host"]["required"]
    event = {"seed_state_refs": ["waiting_for_host"], "included_definition_refs": expected}
    result = audit_definitions(event, oracle)
    assert result["passed"] and result["required_definition_coverage"] == 1
    missing = audit_definitions(event | {"included_definition_refs": expected[1:]}, oracle)
    assert not missing["passed"] and missing["missing_required_refs"]
    extra = audit_definitions(
        event | {"included_definition_refs": expected + ["entities:Unexpected"]}, oracle
    )
    assert extra["irrelevant_definition_count"] == 1 and not extra["passed"]


def test_unmeasured_coverage_is_not_reported_as_perfect():
    assert aggregate_audits([])["required_definition_coverage"] is None
    result = aggregate_audits([{"status": "unmeasured"}])
    assert not result["coverage_complete"] and result["unmeasured_builds"] == 1
    assert result["required_definition_coverage"] is None
    assert (
        audit_definitions({"seed_state_refs": ["unknown"]}, load_oracle(ROOT))["status"]
        == "unmeasured"
    )


def test_full_payload_overflow_is_one_failed_attempt_not_two():
    events = [
        {"event_type": "semantic_context_attempted", "context_attempt_id": "one"},
        {
            "event_type": "semantic_context_built",
            "context_attempt_id": "one",
            "included_bytes": 500,
        },
        {
            "event_type": "guidance_input_measured",
            "context_attempt_id": "one",
            "guidance_input_bytes": 1200,
            "within_budget": False,
        },
        {
            "event_type": "semantic_context_failed",
            "context_attempt_id": "one",
            "error_code": "SEMANTIC_BUDGET_EXCEEDED",
            "model_requested": False,
        },
    ]
    result = semantic_metrics(events)
    assert result["attempts"] == result["failed_attempts"] == 1
    assert result["semantic_fallback_rate"] == 1
    assert result["max_guidance_input_bytes"] == 1200
    assert metrics(events)["usage"]["guidance"]["calls"] == 0
    aggregate = semantic_totals([result, result])
    assert aggregate["attempts"] == 2 and aggregate["semantic_fallback_rate"] == 1


def test_byte_accounting_matches_the_actual_provider_json_body():
    data = {"汉字": ["值", {"nested": 42}]}
    actual = len(json.dumps(data, ensure_ascii=False).encode())
    measured = guidance_budget(data, config(guidance_input_budget_bytes=actual))
    assert measured["guidance_input_bytes"] == actual and measured["within_budget"]
    assert not guidance_budget(data, config(guidance_input_budget_bytes=actual - 1))[
        "within_budget"
    ]


def test_full_payload_matrix_includes_typed_facts_plans_events_and_expected_rejections():
    c = config()
    registry, graph = load_knowledge(ROOT, c)
    report = full_payload_preflight(c, registry, graph, load_oracle(ROOT))
    assert report["passed"]
    assert (
        report["cases"] == 810
        and report["accepted"] == 675
        and report["expected_rejections"] == 135
    )
    assert report["no_model_calls"] and report["no_business_writes"]
    assert all(r["audit"]["passed"] for r in report["results"])
    assert all(r["guidance_input_bytes"] > r["semantic_bytes"] for r in report["results"])
    assert {r["profile"] for r in report["results"]} == {
        "fresh",
        "waiting",
        "conflict",
        "stale",
        "long_fields",
        "oversized",
    }


async def test_actual_runtime_full_input_budget_failure_preserves_guards_and_pairing():
    env = await make_environment(ROOT, case(), "P", reasoning_config=config())
    try:
        await env.prepare()
        client = guide()
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu-1",
                        "name": "get_listing",
                        "input": {"listing_id": "AR-2102"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu-1", "content": "Read complete."}
                ],
            },
        ]
        before = copy.deepcopy(messages)
        await env.service.prepare_request(env.session, messages, client, env.config)
        wire = client.calls[0]["messages"][0]["content"]
        # Static definitions still fit; only the full facts+graph envelope fails.
        env.service.config.guidance_input_budget_bytes = len(wire.encode()) - 1
        result = await env.service.prepare_request(env.session, messages, client, env.config)
        assert len(client.calls) == 1
        assert messages == before and result[-1]["content"][0]["tool_use_id"] == "tu-1"
        assert "guidance_unavailable" in result[-1]["content"][-1]["text"]
        assert env.state.approved_change_ids == set()
        assert env.backend._state_row("AR-2102")["stock"] == 12
        task = env.service.task(env.session)
        m = metrics(
            env.service.store.events(env.session.merchant_id, task.task_id),
            semantic_oracle=load_oracle(ROOT),
        )
        assert m["usage"]["guidance"]["calls"] == 1
        assert m["semantic"]["attempts"] == 2 and m["semantic"]["failed_attempts"] == 1
        assert m["semantic"]["coverage"]["required_definition_coverage"] == 1
    finally:
        env.service.store.close()


async def test_semantic_snapshot_becomes_historical_when_phase_changes():
    env = await make_environment(ROOT, case(), "P", reasoning_config=config(hops=0))
    try:
        await env.prepare()
        task = env.service.task(env.session)
        task.phase = "WAIT_APPROVAL"
        env.service.save_task(task)
        await env.service.prepare_request(env.session, [], guide(), env.config)
        assert env.service.debug_task(env.session, task.task_id)["semantic_context"]["is_current"]
        task.phase, task.host_outcome = "DECLINED", "discarded"
        env.service.save_task(task)
        snapshot = env.service.debug_task(env.session, task.task_id)["semantic_context"]
        assert not snapshot["is_current"] and snapshot["phase"] == "WAIT_APPROVAL"
        other = env.session.model_copy(update={"session_id": "other-session"})
        with pytest.raises(LookupError):
            env.service.debug_task(other, task.task_id)
    finally:
        env.service.store.close()


def test_live_prerequisites_do_not_guess_model_or_leak_secret():
    from commerce_reasoning.live_acceptance import prerequisites

    result = prerequisites({})
    assert result["status"] == "blocked" and result["real_model_calls"] == 0
    assert result["missing"] == ["ANTHROPIC_API_KEY", "COMMERCE_MODEL"]
    result = prerequisites(
        {"ANTHROPIC_API_KEY": "secret-fixture", "COMMERCE_MODEL": "gateway-fixture"}
    )
    assert result["missing"] == ["ANTHROPIC_BASE_URL"]
    assert "secret-fixture" not in json.dumps(result)
    assert (
        prerequisites(
            {
                "ANTHROPIC_API_KEY": "x",
                "COMMERCE_MODEL": "claude-fixture",
                "ANTHROPIC_BASE_URL": "http://remote.invalid",
            }
        )["status"]
        == "blocked"
    )


async def test_live_call_budget_limits_create_and_stream_without_network():
    from commerce_common.testing import FakeClient
    from commerce_reasoning.live_acceptance import (
        BudgetedMessages,
        ModelBudget,
        ModelBudgetExceeded,
    )

    budget = ModelBudget(max_calls=1)
    messages = BudgetedMessages(guide().messages, budget)
    await messages.create(model="fixture", max_tokens=10, messages=[])
    with pytest.raises(ModelBudgetExceeded):
        await messages.create(model="fixture", max_tokens=10, messages=[])
    budget = ModelBudget(max_calls=1)
    streamed = BudgetedMessages(FakeClient([text_message("Fixture")]).messages, budget)
    async with streamed.stream(model="fixture", max_tokens=10, messages=[]) as stream:
        async for _ in stream:
            pass
        await stream.get_final_message()
    assert budget.calls == 1 and budget.tokens == 2 and budget.unmetered_calls == 0
    with pytest.raises(ModelBudgetExceeded):
        streamed.stream(model="fixture", max_tokens=10, messages=[])
