import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from commerce_common.streaming import ToolOutcome
from commerce_common.testing import FakeClient, text_message, tool_calls_message
from commerce_common.turn import EagerDispatcher
from commerce_reasoning.evaluation import make_environment
from merchant_agent_runtime import MerchantAgent

ROOT = Path(__file__).resolve().parents[2]


async def test_serial_dispatch_preserves_order_and_completed_writes_on_cancellation():
    sequence = []
    blocked = asyncio.Event()

    async def execute(name, args):
        sequence.append(name)
        if name == "second":
            await blocked.wait()
        return ToolOutcome(name)

    dispatcher = EagerDispatcher(execute, True, serial=True)
    assert not dispatcher.dispatch("first", "one", {})
    pending = asyncio.create_task(
        dispatcher.collect(
            [
                SimpleNamespace(id="one", name="first", input={}),
                SimpleNamespace(id="two", name="second", input={}),
            ]
        )
    )
    for _ in range(10):
        await asyncio.sleep(0)
        if "second" in sequence:
            break
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert sequence == ["first", "second"]
    assert dispatcher.completed()["one"].result_text == "first"
    dispatcher.cancel()


async def test_runtime_multitool_turn_pairs_results_and_keeps_guidance_out_of_history():
    case = json.loads((ROOT / "evals/commerce_reasoning/tasks/T01.json").read_text())
    env = await make_environment(ROOT, case)
    client = FakeClient(
        [
            tool_calls_message(
                ("get_listing", {"listing_id": "AR-2102"}), ("get_pending_changes", {})
            ),
            tool_calls_message(
                ("calculate_restock_plan", {"listing_id": "AR-2102", "target_days": 30})
            ),
            tool_calls_message(
                (
                    "stage_inventory_action",
                    {"items": [{"listing_id": "AR-2102", "action": "restock", "quantity": 78}]},
                )
            ),
            text_message("补货78件的方案已暂存，等待卡片批准。"),
        ]
    )
    agent = MerchantAgent(
        backend=env.backend,
        config=env.config,
        skills=env.skills,
        client=client,
        execution_service=env.service,
    )
    messages = [{"role": "user", "content": case["task_text"]}]
    events = [event async for event in agent.stream_turn(messages, env.session, env.state)]
    assert env.backend._state_row("AR-2102")["stock"] == 12
    assert env.service.task(env.session).phase == "WAIT_APPROVAL"
    assert "reasoning_advisory_data" not in json.dumps(messages)
    assert all(
        "reasoning_advisory_data" in json.dumps(request["messages"]) for request in client.calls
    )
    previews = [e for e in events if e.type == "ui" and e.data["component"] == "change_preview"]
    assert len(previews) == 1 and len(previews[0].data["payload"]["preview_digest"]) == 64
    for index, message in enumerate(messages):
        calls = (
            [b for b in message["content"] if isinstance(b, dict) and b.get("type") == "tool_use"]
            if isinstance(message["content"], list)
            else []
        )
        if calls:
            assert {b["id"] for b in calls} == {
                b["tool_use_id"] for b in messages[index + 1]["content"]
            }
