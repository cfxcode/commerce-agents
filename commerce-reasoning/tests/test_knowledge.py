import copy
import json
from pathlib import Path

import pytest

from commerce_reasoning.config import ReasoningConfig
from commerce_reasoning.evaluation import FixedClock, make_environment
from commerce_reasoning.evolution import (
    CandidatePatch,
    EvolutionRunner,
    apply_patch,
    validation_gate,
)
from commerce_reasoning.guidance import GuidanceProvider
from commerce_reasoning.models import Blocked, TaskRecord
from commerce_reasoning.procedural import (
    PREDICATES,
    ProcedureGraph,
    SubgraphRetriever,
    load_knowledge,
    predicate,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def knowledge():
    return load_knowledge(ROOT, ReasoningConfig())


def context():
    clock = FixedClock()
    task = TaskRecord(
        merchant_id="m",
        operator="o",
        session_hash="s",
        environment_id="e",
        created_at=clock(),
        updated_at=clock(),
    )
    return {
        "task": task,
        "view": {"listing": None, "observations": {}, "pending": None, "pending_present": None},
        "alerts": {},
    }


@pytest.mark.parametrize("name", sorted(PREDICATES))
def test_predicates_are_total_and_three_valued(name):
    assert predicate(name, context()) in (True, False, None)


def test_pending_unknown_does_not_mean_absent():
    data = context()
    assert predicate("pending_absent", data) is None
    assert predicate("ready_to_calculate", data) is None


def test_locator_uses_semantic_bindings_after_node_replacement(knowledge):
    from commerce_reasoning.procedural import ProcedureLocator

    registry, graph = knowledge
    definition = copy.deepcopy(graph.definition)
    for node in definition["nodes"]:
        if node["id"] == "READ_LISTING":
            node["id"] = "NEW_LISTING_READ"
    for edge in definition["edges"]:
        for endpoint in ("source", "target"):
            if edge[endpoint] == "READ_LISTING":
                edge[endpoint] = "NEW_LISTING_READ"
    changed = ProcedureGraph(definition, graph.schema, registry)
    task = context()["task"]
    task.phase = "READ_LISTING"
    assert ProcedureLocator.locate(task, changed) == ("NEW_LISTING_READ", False)
    definition["nodes"][0]["kind"] = "action"
    with pytest.raises(ValueError, match="Node kind"):
        ProcedureGraph(definition, graph.schema, registry)


def test_graph_references_reachability_cycles_and_bfs(knowledge):
    registry, graph = knowledge
    assert len(graph.nodes) == 15 and len(graph.edges) == 22
    result = SubgraphRetriever().retrieve(graph, "START", context(), budget=8000)
    assert "START" in {n["id"] for n in result["nodes"]}
    assert not any(e["source"] == "CALCULATE" for e in result["edges"])
    for edge in result["edges"]:
        assert {edge["source"], edge["target"]} <= {n["id"] for n in result["nodes"]}
    broken = copy.deepcopy(graph.definition)
    broken["edges"][0]["target"] = "missing"
    with pytest.raises(ValueError):
        ProcedureGraph(broken, graph.schema, registry)
    with pytest.raises(ValueError):
        graph.validate_enabled({"get_listing"})
    with pytest.raises(ValueError):
        SubgraphRetriever().retrieve(graph, "START", context(), budget=1)


def test_guidance_rejects_fabricated_evidence_actions_and_instructions():
    data = {"enabled_actions": ["ReadListing"], "edge_ids": ["E01"], "evidence_ids": ["obs1"]}
    base = {"immediate_goal": "Read the listing", "recommended_action_refs": ["ReadListing"]}
    assert GuidanceProvider.validate(base, data).immediate_goal
    for invalid in (
        {"required_evidence_ids": ["invented"]},
        {"used_edge_ids": ["bad"]},
        {"recommended_action_refs": ["ApplyApprovedChange"]},
        {"immediate_goal": "已批准"},
    ):
        with pytest.raises(Blocked):
            GuidanceProvider.validate(base | invalid, data)


def patch_for(graph):
    return {
        "base_version": graph.definition["version"],
        "base_hash": graph.content_hash,
        "edit_id": "test-edit",
        "rationale": "A synthetic lifecycle test; not a measured improvement.",
        "training_evidence_ids": ["synthetic-training"],
        "operations": [{"op": "update_edge_attributes", "id": "E01", "value": {"priority": 11}}],
    }


def test_candidate_cannot_edit_rules_and_leaves_original_immutable(knowledge, tmp_path):
    _, graph = knowledge
    original = copy.deepcopy(graph.definition)
    proposal = patch_for(graph)
    candidate = apply_patch(graph, CandidatePatch.model_validate(proposal))
    assert candidate.content_hash != graph.content_hash and graph.definition == original
    proposal["operations"][0]["value"] = {"host_approval": False}
    result = EvolutionRunner(tmp_path, graph).consider(proposal)
    assert result["status"] == "rejected" and graph.definition == original


def validation_report():
    return {
        "manifest_hash": "test-only",
        "model": "fake",
        "environment_hash": "e",
        "config_hash": "c",
        "role": "validation",
        "repetitions": 3,
        "safety_violations": 0,
        "safety_regression_passed": True,
        "valid": 6,
        "submitted": 6,
        "success_rate": 1,
        "critical_failures": {},
        "total_tokens": 100,
    }


def test_synthetic_accept_reject_deduplicate_and_cost_gate(knowledge, tmp_path):
    _, graph = knowledge
    runner = EvolutionRunner(tmp_path, graph)
    evidence = validation_report()
    accepted = runner.consider(patch_for(graph), baseline=evidence, validation=evidence)
    assert accepted["status"] == "accepted"
    assert runner.consider(patch_for(graph))["reasons"] == ["equivalent_candidate"]
    assert not validation_gate(evidence, evidence | {"safety_violations": 1})[0]
    assert not validation_gate(evidence, evidence | {"total_tokens": 151})[0]
    assert not validation_gate(evidence, evidence | {"repetitions": 1})[0]


async def test_CQ01_through_CQ08_are_answered_without_a_model(knowledge):
    registry, _ = knowledge
    case = json.loads((ROOT / "evals/commerce_reasoning/tasks/T01.json").read_text())
    env = await make_environment(ROOT, case)
    executor = await env.prepare()
    plain = await env.backend.get_listing(env.session, "AR-2102")
    family = await env.backend.get_listing(env.session, "AR-1902")
    variant = await env.backend.get_listing(env.session, "AR-1902-QUEEN")
    assert [registry.classify(x) for x in (plain, family, variant)] == [
        "SellableItem",
        "ProductFamily",
        "Variant",
    ]  # CQ01
    assert registry.related(variant, env.session.merchant_id)[1]["target"] == family.listing_id
    await executor.execute("get_inventory_alerts", {})
    observations = env.service.store.list("observations", env.session.merchant_id)
    assert any(
        o["field"] == "alert_for" and o["entity_ref"]["object_type"] == "InventoryAlert"
        for o in observations
    )  # CQ02
    view = env.service.adapter.view(env.service.task(env.session), env.clock())
    assert view["observations"]["stock"]["source_tool"] == "get_listing"  # CQ03
    assert view["observations"]["stock"]["value_status"] == "known"  # CQ04
    assert view["pending_present"] is False and view["pending_current"]  # CQ05
    contract = registry.contract("StageRestock")
    assert contract["effect"] == "create_staged_change_only"  # CQ06/07
    assert {"VALID_TARGET", "PLAN_MATCH"} <= set(contract["checks"])  # CQ08
    # CQ09/10 exercise real approval digest and receipt evidence in test_execution.
