"""Closure integration is tested with fake models and the real guarded retail tools."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from commerce_common.testing import FakeClient, FakeCreateClient, text_message, tool_calls_message
from commerce_reasoning.config import ReasoningConfig
from commerce_reasoning.evaluation import make_environment, metrics
from commerce_reasoning.guidance import GuidanceProvider
from commerce_reasoning.models import Blocked
from merchant_agent_runtime import MerchantAgent

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "fixtures/semantic_context/expected/legacy-start-requests.json"


def case():
    return json.loads((ROOT / "evals/commerce_reasoning/tasks/T01.json").read_text())


def closure_config(**updates):
    return ReasoningConfig(
        semantic_context_mode="closure",
        semantic_budget_bytes=16000,
        guidance_input_budget_bytes=30000,
        **updates,
    )


def guide_client(count=1):
    return FakeCreateClient(
        [text_message('{"immediate_goal":"Read current evidence.","recommended_action_refs":[]}')]
        * count
    )


@pytest.fixture(scope="module")
def legacy_requests():
    script = GOLDEN.parent.parent / "capture_legacy.py"
    output = subprocess.check_output(
        [sys.executable, str(script)],
        cwd=ROOT,
        text=True,
        env=os.environ | {"PYTHONHASHSEED": "0", "COMMERCE_MODEL": "claude-opus-5"},
    )
    return json.loads(output)


@pytest.mark.parametrize("variant", ["C0", "O", "T", "P"])
def test_legacy_start_matches_unmodified_adf2337_golden(variant, legacy_requests):
    # Full request bytes, including set-derived action order, are captured in a
    # fixed interpreter hash-seed process. No semantic fields are normalized away.
    assert legacy_requests[variant] == json.loads(GOLDEN.read_text())[variant]


@pytest.mark.parametrize("variant", ["T", "P", "E"])
async def test_closure_consumed_by_guide_not_duplicated_in_solver(variant):
    env = await make_environment(ROOT, case(), variant, reasoning_config=closure_config())
    try:
        await env.service.begin_turn(env.session, case()["task_text"])
        messages = [{"role": "user", "content": "Check inventory."}]
        original = copy.deepcopy(messages)
        client = guide_client()
        result = await env.service.prepare_request(env.session, messages, client, env.config)
        data = json.loads(client.calls[0]["messages"][0]["content"])
        assert data["semantic_definitions"]["actions"]
        assert data["semantic_definitions"]["states"]
        assert "action_contracts" not in data
        assert messages == original
        assert "semantic_definitions" not in json.dumps(result)
        assert "procedural_guidance" in json.dumps(result)
        assert ("steps" in data) == (variant == "T")
        assert ("subgraph" in data) == (variant != "T")
        assert "dependency_paths" not in json.dumps(data)
        if variant == "T":
            assert "current_node" not in json.dumps(data)
            assert '"source"' not in json.dumps(data)
        assert env.state.approved_change_ids == set()
        assert env.service.task(env.session).phase == "START"
        assert data["semantic_context"]["target_kind"] == "unknown"
        assert data["semantic_context"]["facts"] == {}
    finally:
        env.service.store.close()


async def test_t_and_p_receive_identical_semantic_definitions():
    definitions = []
    for variant in ("T", "P"):
        env = await make_environment(ROOT, case(), variant, reasoning_config=closure_config())
        try:
            await env.service.begin_turn(env.session, case()["task_text"])
            client = guide_client()
            await env.service.prepare_request(env.session, [], client, env.config)
            definitions.append(
                json.loads(client.calls[0]["messages"][0]["content"])["semantic_definitions"]
            )
        finally:
            env.service.store.close()
    assert definitions[0] == definitions[1]


async def test_waiting_state_hops_zero_does_not_grant_authority():
    env = await make_environment(ROOT, case(), "P", reasoning_config=closure_config(hops=0))
    try:
        await env.prepare()
        task = env.service.task(env.session)
        task.phase = "WAIT_APPROVAL"
        env.service.save_task(task)
        client = guide_client()
        await env.service.prepare_request(env.session, [], client, env.config)
        data = json.loads(client.calls[0]["messages"][0]["content"])
        assert data["enabled_actions"] == []
        assert data["semantic_definitions"]["actions"] == []
        assert {s["id"] for s in data["semantic_definitions"]["states"]} == {"waiting_for_host"}
        assert {e["id"] for e in data["semantic_definitions"]["entities"]} >= {
            "ApprovalRecord",
            "Operator",
        }
        assert not env.state.approved_change_ids
        assert env.service.task(env.session).phase == "WAIT_APPROVAL"
        with pytest.raises(Blocked):
            GuidanceProvider.validate(
                {"immediate_goal": "Apply", "recommended_action_refs": ["ApplyApprovedChange"]},
                data,
            )
    finally:
        env.service.store.close()


@pytest.mark.parametrize("which", ["semantic_budget_bytes", "guidance_input_budget_bytes"])
async def test_pre_model_budget_failure_is_not_a_model_call(which):
    config = closure_config()
    config = config.model_copy(update={which: 1})
    env = await make_environment(ROOT, case(), "P", reasoning_config=config)
    try:
        await env.service.begin_turn(env.session, case()["task_text"])
        client = guide_client()
        result = await env.service.prepare_request(env.session, [], client, env.config)
        assert client.calls == []
        assert "guidance_unavailable" in json.dumps(result)
        task = env.service.task(env.session)
        events = env.service.store.events(task.merchant_id, task.task_id)
        failure = next(e for e in events if e["event_type"] == "semantic_context_failed")
        assert failure["model_requested"] is False
        assert "usage_known" not in failure
        assert metrics(events)["usage"]["guidance"]["calls"] == 0
        assert metrics(events)["unmetered_calls"] == 0
        assert env.service.debug_task(env.session, task.task_id)["semantic_context"] is None
        result = await env.executor().execute("apply_change", {"change_id": "invented"})
        assert result.blocked or result.is_error
        assert env.backend._state_row("AR-2102")["stock"] == 12
    finally:
        env.service.store.close()


async def test_matrix_checked_after_evaluation_override():
    # The evaluator intentionally disables C0; effective mode must then be legacy.
    env = await make_environment(ROOT, case(), "C0", reasoning_config=closure_config(enabled=True))
    assert env.service.config.effective_semantic_mode == "legacy"
    env.service.store.close()
    with pytest.raises(ValueError, match="closure requires"):
        await make_environment(ROOT, case(), "O", reasoning_config=closure_config(enabled=True))


def test_disabled_closure_is_effectively_legacy_and_copy_updates_are_revalidated():
    disabled = closure_config(enabled=False, variant="C0").validate_effective()
    assert disabled.effective_semantic_mode == "legacy"
    assert disabled.effective_variant == "C0"
    invalid = disabled.model_copy(update={"enabled": True})
    with pytest.raises(ValueError, match="closure requires"):
        invalid.validate_effective()


async def test_new_debug_field_retains_task_and_session_scope():
    env = await make_environment(ROOT, case(), "P", reasoning_config=closure_config())
    try:
        await env.service.begin_turn(env.session, case()["task_text"])
        await env.service.prepare_request(env.session, [], guide_client(), env.config)
        task = env.service.task(env.session)
        detail = env.service.debug_task(env.session, task.task_id)
        assert detail["semantic_context"]["diagnostics"]["dependency_paths"]
        assert "implementation" not in json.dumps(detail["semantic_context"]["public"])
        with pytest.raises(LookupError):
            env.service.debug_task(
                env.session.model_copy(update={"session_id": "other"}), task.task_id
            )
        with pytest.raises(LookupError):
            env.service.debug_task(
                env.session.model_copy(update={"merchant_id": "other"}), task.task_id
            )
    finally:
        env.service.store.close()


async def test_tool_result_pairing_and_history_unchanged_with_closure():
    env = await make_environment(ROOT, case(), "P", reasoning_config=closure_config())
    # Separate fake create/stream paths model the guide and the solver on one client.
    client = FakeClient(
        [
            tool_calls_message(
                ("get_listing", {"listing_id": "AR-2102"}), ("get_pending_changes", {})
            ),
            text_message("Current evidence has been read; no inventory write."),
        ]
    )
    create = guide_client(5)
    client.messages.create = create.messages.create
    agent = MerchantAgent(
        backend=env.backend,
        config=env.config,
        skills=env.skills,
        client=client,
        execution_service=env.service,
    )
    try:
        messages = [{"role": "user", "content": case()["task_text"]}]
        _events = [event async for event in agent.stream_turn(messages, env.session, env.state)]
        assert create.calls
        assert "semantic_definitions" not in json.dumps(messages)
        assert "reasoning_advisory_data" not in json.dumps(messages)
        for index, message in enumerate(messages):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            calls = [b["id"] for b in content if b.get("type") == "tool_use"]
            if calls:
                assert set(calls) == {b["tool_use_id"] for b in messages[index + 1]["content"]}
        assert env.backend._state_row("AR-2102")["stock"] == 12
    finally:
        env.service.store.close()
