"""Loopback-only browser fixture: real retail tools/approval routes, scripted models.

Never imported by production entry points. No API credentials are read, and no
network model client is constructed. Restart the process for each isolated case.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))


async def create_app(degraded: bool = False):
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from commerce_common.testing import (
        FakeClient,
        FakeCreateClient,
        text_message,
        tool_calls_message,
    )
    from commerce_reasoning.config import ReasoningConfig
    from commerce_reasoning.evaluation import make_environment
    from demo_common.merchant import MerchantIdentity, build_merchant_router
    from merchant_agent_runtime import MerchantAgent

    case = json.loads((ROOT / "evals/commerce_reasoning/tasks/T01.json").read_text())
    config = ReasoningConfig.from_file(ROOT / "configs/experiments/p-closure.yaml")
    if degraded:
        config.semantic_budget_bytes = 64
    env = await make_environment(ROOT, case, "P", reasoning_config=config)

    class FixtureAgent(MerchantAgent):
        async def stream_turn(self, messages, session, state=None):
            solver = FakeClient(
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
                            {
                                "items": [
                                    {"listing_id": "AR-2102", "action": "restock", "quantity": 78}
                                ]
                            },
                        )
                    ),
                    text_message(
                        "补货78件的方案已暂存，等待卡片批准。"
                        if session.response_language == "Simplified Chinese"
                        else "The 78-unit proposal is staged. Awaiting approval on the card."
                    ),
                ]
            )
            guide = FakeCreateClient(
                [
                    text_message(
                        '{"immediate_goal":"Use verified evidence and wait for the host after staging.","recommended_action_refs":[]}'
                    )
                ]
                * 20
            )
            solver.messages.create = guide.messages.create
            self.client = solver
            async for event in super().stream_turn(messages, session, state):
                yield event

    agent = FixtureAgent(
        backend=env.backend,
        skills=env.skills,
        config=env.config,
        client=FakeClient([]),
        execution_service=env.service,
    )
    app = FastAPI(title="ISOLATED semantic browser fixture — scripted models")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3100", "http://127.0.0.1:3100"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(
        build_merchant_router(
            storefront=env.backend.storefront,
            backend=env.backend,
            agent=agent,
            identity=MerchantIdentity(merchant_id="acme-retail", operator="evaluation-operator"),
            example_dir="retail",
            overview_extras=lambda: {
                "trends": env.backend.kpi_trends(),
                "trends_prior": env.backend.kpi_trends(periods_back=1),
                "insights": env.backend.home_insights(),
            },
        ),
        prefix="/api/merchant",
    )

    @app.get("/__test__/state")
    async def state():
        tasks = env.service.store.list("tasks", "acme-retail")
        return {
            "fixture": True,
            "real_model_calls": 0,
            "stock": env.backend._state_row("AR-2102")["stock"],
            "phases": [t["phase"] for t in tasks],
            "pending": len(env.backend.ledger.pending()),
            "degraded_fixture": degraded,
        }

    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--degraded", action="store_true")
    args = parser.parse_args()
    uvicorn.run(
        asyncio.run(create_app(args.degraded)), host="127.0.0.1", port=8000, log_level="warning"
    )
