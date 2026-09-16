import asyncio
import json
import sys
from pathlib import Path

from commerce_common.testing import FakeCreateClient, text_message
from commerce_reasoning.config import ReasoningConfig
from commerce_reasoning.evaluation import make_environment

root = Path(__file__).resolve().parents[4]
# pytest.ini adds examples only to the parent interpreter; this helper is a child.
sys.path.insert(0, str(root / "examples"))


async def run():
    case = json.loads((root / "evals/commerce_reasoning/tasks/T01.json").read_text())
    out = {}
    for variant in ("C0", "O", "T", "P"):
        env = await make_environment(root, case, variant, reasoning_config=ReasoningConfig())
        await env.service.begin_turn(env.session, case["task_text"])
        client = FakeCreateClient(
            [
                text_message(
                    '{"immediate_goal":"Read current evidence.","recommended_action_refs":[]}'
                )
            ]
        )
        messages = [{"role": "user", "content": "Check inventory."}]
        result = await env.service.prepare_request(env.session, messages, client, env.config)
        out[variant] = {"guide_requests": client.calls, "solver_messages": result}
        env.service.store.close()
    print(json.dumps(out, ensure_ascii=False))


asyncio.run(run())
