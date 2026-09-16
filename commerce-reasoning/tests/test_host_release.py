import json
import shutil
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from commerce_common.testing import FakeClient, text_message, tool_calls_message
from commerce_reasoning.config import ReasoningConfig
from commerce_reasoning.evaluation import make_environment
from commerce_reasoning.evolution import activate, publish, validate_splits, verify_release
from commerce_reasoning.procedural import load_knowledge
from demo_common.merchant import MerchantIdentity, build_merchant_router
from merchant_agent_runtime import MerchantAgent

ROOT = Path(__file__).resolve().parents[2]


async def test_host_preview_digest_task_scope_and_same_service_apply():
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
            text_message("等待卡片批准。"),
        ]
    )
    agent = MerchantAgent(
        backend=env.backend,
        skills=env.skills,
        config=env.config,
        client=client,
        execution_service=env.service,
    )
    app = FastAPI()
    app.include_router(
        build_merchant_router(
            storefront=env.backend.storefront,
            backend=env.backend,
            agent=agent,
            identity=MerchantIdentity(merchant_id="acme-retail", operator="evaluation-operator"),
            example_dir="retail",
        ),
        prefix="/api/merchant",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://localhost"
    ) as http:
        response = await http.post("/api/merchant/session")
        headers = {"X-Session-Id": response.json()["session_id"]}
        assert (await http.get("/api/merchant/reasoning/tasks")).status_code == 401
        response = await http.post(
            "/api/merchant/chat",
            headers=headers,
            json={"message": case["task_text"], "locale": "zh-CN"},
        )
        assert response.status_code == 200
        blocks = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        preview = next(b["payload"] for b in blocks if b.get("component") == "change_preview")
        tasks = (await http.get("/api/merchant/reasoning/tasks", headers=headers)).json()["tasks"]
        assert len(tasks) == 1
        detail = (
            await http.get(f"/api/merchant/reasoning/tasks/{tasks[0]['task_id']}", headers=headers)
        ).json()
        assert detail["plan"]["quantity"] == 78
        other = (await http.post("/api/merchant/session")).json()["session_id"]
        assert (
            await http.get(
                f"/api/merchant/reasoning/tasks/{tasks[0]['task_id']}",
                headers={"X-Session-Id": other},
            )
        ).status_code == 404
        path = f"/api/merchant/changes/{preview['change_id']}/apply"
        assert not (await http.post(path, headers=headers)).json()["ok"]
        assert (
            await http.post(
                path, headers=headers, json={"preview_digest": preview["preview_digest"]}
            )
        ).json()["ok"]
        assert env.backend._state_row("AR-2102")["stock"] == 90
        assert (
            await http.post(
                path, headers=headers, json={"preview_digest": preview["preview_digest"]}
            )
        ).json()["ok"]
        assert env.backend._state_row("AR-2102")["stock"] == 90


def test_release_hashes_immutability_and_rollback(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "knowledge", tmp_path / "knowledge")
    config = ReasoningConfig()
    _, graph = load_knowledge(tmp_path, config)
    evidence = tmp_path / "safety.json"
    evidence.write_text(
        json.dumps(
            {
                "run_id": "synthetic-release-test",
                "graph_hash": graph.content_hash,
                "safety_regression_passed": True,
            }
        )
    )
    # This is a publication mechanism test, not a claim of human or model validation.
    monkeypatch.setattr(
        "commerce_reasoning.evolution.subprocess.check_output",
        lambda *args, **kwargs: "synthetic-commit",
    )
    first = publish(
        tmp_path,
        graph=graph,
        config=config,
        approved_by="synthetic-test-reviewer",
        validation_path=evidence,
        initial=True,
    )
    second = publish(
        tmp_path,
        graph=graph,
        config=config,
        approved_by="synthetic-test-reviewer",
        validation_path=evidence,
        initial=True,
    )
    assert first["release_id"] != second["release_id"]
    first_path = tmp_path / "knowledge/releases" / first["release_id"] / "manifest.json"
    activate(tmp_path, first_path)
    assert (
        verify_release(tmp_path, tmp_path / "knowledge/releases/active.json")["release_id"]
        == first["release_id"]
    )
    (tmp_path / first["knowledge_paths"]["pg_path"]).write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_release(tmp_path, first_path)


def test_evolution_splits_are_group_disjoint():
    validate_splits(
        ROOT,
        [
            ROOT / f"evals/commerce_reasoning/manifests/{name}.json"
            for name in ("training", "validation", "test")
        ],
    )
