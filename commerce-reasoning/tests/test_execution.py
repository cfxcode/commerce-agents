"""State assertions for the specification's T01–T24, not model self-report."""

import asyncio
import json
from pathlib import Path

import pytest

from commerce_reasoning.evaluation import make_environment
from commerce_reasoning.models import Blocked, change_digest, uid
from merchant_agent import MerchantSessionContext, MerchantSessionState

ROOT = Path(__file__).resolve().parents[2]


async def environment(case_id="T01"):
    return await make_environment(
        ROOT, json.loads((ROOT / f"evals/commerce_reasoning/tasks/{case_id}.json").read_text())
    )


async def staged(env):
    ex = await env.prepare()
    target = env.case["target"]
    outcome = await ex.execute("calculate_restock_plan", {"listing_id": target, "target_days": 30})
    assert not outcome.refused, outcome.result_text
    plan = env.service.current_plan(env.service.task(env.session))
    outcome = await ex.execute(
        "stage_inventory_action",
        {"items": [{"listing_id": target, "action": "restock", "quantity": plan.quantity}]},
    )
    assert not outcome.refused, outcome.result_text
    return env.backend.ledger.pending()[-1]


async def test_T01_calculation_preview_apply_and_verified_effect():
    env = await environment()
    change = await staged(env)
    assert change.created_at == env.clock()
    assert change.items[0].after == 90 and change.items[0].before == 12
    assert (await env.backend.get_listing(env.session, "AR-2102")).stock == 12
    applied = await env.approve(change.change_id)
    assert not applied.refused, applied.result_text
    assert env.backend.ledger.get(change.change_id).applied_at == env.clock()
    assert (await env.backend.get_listing(env.session, "AR-2102")).stock == 90
    assert env.service.task(env.session).phase == "SUCCESS"
    assert not env.state.approved_change_ids


async def test_T02_variant_only_and_paused_status_preserved():
    env = await environment("T02")
    before = dict(env.backend._state_row("AR-1902-TWIN"))
    env.backend._state_row("AR-1902-QUEEN")["status"] = "paused"
    change = await staged(env)
    assert not (await env.approve(change.change_id)).refused
    assert env.backend._inventory["AR-1902-TWIN"] == before
    assert env.backend._state_row("AR-1902-QUEEN")["status"] == "paused"


@pytest.mark.parametrize(
    "case_id,code",
    [
        ("T03", "INVALID_TARGET_KIND"),
        ("T05", "MISSING_SALES_HISTORY"),
        ("T08", "PENDING_CHANGE_CONFLICT"),
        ("T10", "INCOMPLETE_SNAPSHOT"),
        ("T11", "STALE_OBSERVATION"),
        ("T12", "GUARDRAIL_BLOCKED"),
    ],
)
async def test_invalid_evidence_and_policy_block_calculation(case_id, code):
    env = await environment(case_id)
    ex = await env.prepare()
    result = await ex.execute(
        "calculate_restock_plan", {"listing_id": env.case["target"], "target_days": 30}
    )
    assert result.blocked == code, result.result_text


async def test_T04_alerts_do_not_grant_full_listing_provenance():
    env = await environment()
    await env.service.begin_turn(env.session, env.case["task_text"])
    ex = env.executor()
    await ex.execute("get_inventory_alerts", {})
    await ex.execute("get_pending_changes", {})
    assert "AR-2102" not in env.state.seen_listings
    result = await ex.execute(
        "calculate_restock_plan", {"listing_id": "AR-2102", "target_days": 30}
    )
    assert result.blocked == "MISSING_FULL_READ"


@pytest.mark.parametrize("case_id", ["T06", "T07"])
async def test_zero_quantity_never_stages(case_id):
    env = await environment(case_id)
    ex = await env.prepare()
    await ex.execute("calculate_restock_plan", {"listing_id": "AR-2102", "target_days": 30})
    plan = env.service.current_plan(env.service.task(env.session))
    assert plan.quantity == 0
    result = await ex.execute(
        "stage_inventory_action",
        {"items": [{"listing_id": "AR-2102", "action": "restock", "quantity": 0}]},
    )
    assert result.refused and not env.backend.ledger.pending()


async def test_T09_seen_changes_is_not_the_current_queue():
    env = await environment("T09")
    assert env.state.seen_changes
    change = await staged(env)
    assert change.items[0].after - change.items[0].before == 77


async def test_T10_failed_queue_preserves_history_but_invalidates_currentness():
    env = await environment()
    await env.prepare()
    task = env.service.task(env.session)
    env.service.adapter.failed(task, "get_pending_changes")
    view = env.service.adapter.view(task, env.clock())
    assert view["pending"] and not view["pending_current"] and view["pending_present"] is None


@pytest.mark.parametrize("case_id", ["T13", "T14"])
async def test_injection_and_chat_do_not_authorize_apply(case_id):
    env = await environment(case_id)
    change = await staged(env)
    result = await env.executor().execute("apply_change", {"change_id": change.change_id})
    assert result.blocked == "HOST_APPROVAL_REQUIRED"
    assert env.backend._state_row("AR-2102")["stock"] == 12


async def test_T15_same_service_host_origin_and_approval_evidence():
    env = await environment()
    change = await staged(env)
    await env.approve(change.change_id)
    approval = env.service.store.get("approvals", env.session.merchant_id, change.change_id)
    assert approval["consumed"] and approval["payload_digest"] == change_digest(change)
    assert approval["operator"] == env.session.operator


async def test_T16_discard_does_not_apply_or_recreate():
    env = await environment()
    change = await staged(env)
    await env.approve(change.change_id, discard=True)
    assert env.backend._state_row("AR-2102")["stock"] == 12
    assert env.service.task(env.session).phase == "DECLINED"
    assert not env.backend.ledger.pending()
    assert (
        await env.executor().execute(
            "calculate_restock_plan", {"listing_id": "AR-2102", "target_days": 30}
        )
    ).blocked == "HOST_DECLINED"


async def test_T17_preview_digest_and_task_revision_bind_approval():
    env = await environment()
    change = await staged(env)
    change.items[0].after += 1
    assert (await env.approve(change.change_id)).blocked == "APPROVAL_DIGEST_MISMATCH"
    change.items[0].after -= 1
    await env.service.begin_turn(env.session, "把 AR-2102 改为覆盖15天")
    assert (await env.approve(change.change_id)).blocked == "STALE_PLAN"


async def test_T18_concurrent_duplicate_apply_has_one_effect():
    env = await environment()
    change = await staged(env)
    results = await asyncio.gather(env.approve(change.change_id), env.approve(change.change_id))
    assert all(not r.refused for r in results), [r.result_text for r in results]
    assert env.backend._state_row("AR-2102")["stock"] == 90
    assert len(env.backend.ledger.applied()) == 1


async def test_T19_two_tasks_racing_to_stage_only_create_one_change():
    env = await environment()
    ex1 = await env.prepare()
    await ex1.execute("calculate_restock_plan", {"listing_id": "AR-2102", "target_days": 30})
    second = env.session.model_copy(update={"session_id": "other-session"})
    await env.service.begin_turn(second, env.case["task_text"])
    ex2 = env.executor(session=second, state=MerchantSessionState())
    await ex2.execute("get_listing", {"listing_id": "AR-2102"})
    await ex2.execute("get_pending_changes", {})
    await ex2.execute("calculate_restock_plan", {"listing_id": "AR-2102", "target_days": 30})
    args = {"items": [{"listing_id": "AR-2102", "action": "restock", "quantity": 78}]}
    outcomes = await asyncio.gather(
        ex1.execute("stage_inventory_action", args), ex2.execute("stage_inventory_action", args)
    )
    assert sum(not o.refused for o in outcomes) == 1
    assert len(env.backend.ledger.pending()) == 1


async def test_T20_revision_changed_after_preview_blocks_apply():
    env = await environment()
    change = await staged(env)
    env.backend.revisions["AR-2102"] = 2
    assert (await env.approve(change.change_id)).blocked == "STALE_TARGET_REVISION"
    assert env.backend._state_row("AR-2102")["stock"] == 12


async def test_T21_lost_response_never_reapplies_and_read_reconciles():
    env = await environment("T21")
    change = await staged(env)
    outcome = await env.approve(change.change_id)
    assert outcome.blocked == "ACTION_OUTCOME_UNKNOWN"
    assert env.service.task(env.session).phase == "RECONCILE"
    assert (await env.approve(change.change_id)).blocked == "ACTION_OUTCOME_UNKNOWN"
    await env.executor().execute("get_listing", {"listing_id": "AR-2102"})
    assert env.service.task(env.session).phase == "SUCCESS"
    assert env.backend._state_row("AR-2102")["stock"] == 90


async def test_T22_commit_failure_leaves_ledger_and_inventory_unchanged():
    env = await environment("T22")
    change = await staged(env)
    assert (await env.approve(change.change_id)).blocked == "FAILED_NO_EFFECT"
    assert env.backend.ledger.get(change.change_id).status.value == "staged"
    assert env.backend._state_row("AR-2102")["stock"] == 12


async def test_T23_guidance_failure_does_not_relax_checks_or_mutate_messages():
    env = await environment()
    env.service.config.enabled = True
    await env.service.begin_turn(env.session, env.case["task_text"])

    async def unavailable(*args, **kwargs):
        raise TimeoutError()

    env.service.guidance.build = unavailable
    messages = [{"role": "user", "content": "hello"}]
    request = await env.service.prepare_request(env.session, messages, None, env.config)
    assert request != messages and messages == [{"role": "user", "content": "hello"}]
    result = await env.executor().execute(
        "stage_inventory_action",
        {"items": [{"listing_id": "AR-2102", "action": "restock", "quantity": 78}]},
    )
    assert result.refused


async def test_T24_cross_tenant_reads_and_tasks_are_rejected():
    env = await environment()
    other = MerchantSessionContext(merchant_id="other", operator="other", session_id="other")
    with pytest.raises(Blocked, match="scope"):
        await env.backend.get_listing(other, "AR-2102")
    await env.prepare()
    with pytest.raises(LookupError):
        env.service.debug_task(other, env.service.task(env.session).task_id)


async def test_missing_days_requires_clarification_and_model_cannot_supply_them():
    env = await environment()
    await env.service.begin_turn(env.session, "请补货 AR-2102")
    result = await env.executor().execute(
        "calculate_restock_plan", {"listing_id": "AR-2102", "target_days": 30}
    )
    assert result.blocked == "PLAN_MISMATCH"
    assert env.service.task(env.session).target_days is None


async def test_same_revision_contradiction_is_not_silently_overwritten():
    env = await environment()
    ex = await env.prepare()
    env.backend._state_row("AR-2102")["stock"] += 1
    await ex.execute("get_listing", {"listing_id": "AR-2102"})
    task = env.service.task(env.session)
    assert (
        env.service.adapter.view(task, env.clock())["observations"]["stock"]["value_status"]
        == "conflicting"
    )
    result = await ex.execute(
        "calculate_restock_plan", {"listing_id": "AR-2102", "target_days": 30}
    )
    assert result.blocked == "STALE_OBSERVATION"


async def test_stale_inputs_allow_only_one_recovery_read_per_turn():
    env = await environment("T11")
    ex = await env.prepare()
    for _ in range(2):
        await ex.execute("calculate_restock_plan", {"listing_id": "AR-2102", "target_days": 30})
        result = await ex.execute("get_listing", {"listing_id": "AR-2102"})
    assert result.blocked == "RECOVERY_BUDGET_EXHAUSTED"
    assert env.service.task(env.session).recovery_reads == 1


@pytest.mark.parametrize(
    "message", ["AR-2102 改成覆盖0天", "改为 AR-2102 和 AR-2106 两个商品，覆盖30天"]
)
async def test_invalid_or_ambiguous_task_revision_invalidates_old_approval(message):
    env = await environment()
    change = await staged(env)
    await env.service.begin_turn(env.session, message)
    assert (await env.approve(change.change_id)).blocked == "STALE_PLAN"
    assert env.backend._state_row("AR-2102")["stock"] == 12


async def test_host_action_does_not_replace_the_current_conversation_task():
    env = await environment()
    change = await staged(env)
    old = env.service.task(env.session)
    current = old.model_copy(update={"task_id": uid("task"), "target": "AR-2106", "phase": "START"})
    env.service.save_task(current, activate=True)
    assert not (await env.approve(change.change_id)).refused
    assert env.service.task(env.session).task_id == current.task_id
    assert (
        env.service.store.get("tasks", env.session.merchant_id, old.task_id)["phase"] == "SUCCESS"
    )
