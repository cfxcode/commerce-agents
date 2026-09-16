"""Independent expected closures and deterministic, atomic budget handling."""

import copy
import json
import socket
from collections import deque
from pathlib import Path

import pytest

from commerce_reasoning.semantic_context import SemanticContextBuilder
from commerce_reasoning.semantic_models import (
    SemanticDefinitionLimits,
    SemanticError,
    canonical_json,
)
from commerce_reasoning.semantic_registry import SemanticRegistry, load_unique_yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def definition():
    return load_unique_yaml(ROOT / "knowledge/ontology/retail.v1.yaml")


def one_node(identifier="STAGE", ref="StageRestock", kind="action"):
    field = "action_ref" if kind == "action" else "state_ref"
    return {
        "current_node": identifier,
        "nodes": [{"id": identifier, "kind": kind, field: ref}],
        "edges": [],
    }


def build(definition, subgraph=None, observed=(), **limits):
    return SemanticContextBuilder().build(
        registry=SemanticRegistry(definition),
        subgraph=subgraph or one_node(),
        observed_type_ids=observed,
        limits=SemanticDefinitionLimits(**limits),
    )


def without_optional(definition):
    definition = copy.deepcopy(definition)
    for kind in ("actions", "states"):
        for item in definition[kind]:
            item["semantic_refs"]["optional"] = {
                k: [] for k in ("entities", "relations", "properties")
            }
    return definition


def ids(bundle, kind):
    return {item["id"] for item in bundle.public[kind]}


def test_stage_required_closure_uses_hand_written_oracle(definition):
    bundle = build(without_optional(definition))
    assert ids(bundle, "actions") == {"StageRestock"}
    assert ids(bundle, "states") == set()
    assert ids(bundle, "entities") == {"Listing", "SellableItem", "RestockPlan", "StagedChange"}
    assert ids(bundle, "relations") == {"plan_for", "change_targets", "realized_by"}
    assert ids(bundle, "properties") == {
        "RestockPlan.quantity",
        "RestockPlan.status",
        "StagedChange.status",
    }
    assert ids(bundle, "checks") == {
        "TENANT_SCOPE",
        "UPSTREAM_PROVENANCE",
        "VALID_TARGET",
        "PLAN_MATCH",
        "PENDING_CONFLICT_ATOMIC",
        "UPSTREAM_GUARDRAILS",
    }
    assert bundle.diagnostics["required_definition_count"] == 17
    assert bundle.diagnostics["optional_definition_count"] == 0


def test_waiting_state_without_actions_or_hops(definition):
    node = one_node("WAIT_APPROVAL", "waiting_for_host", "state")
    bundle = build(without_optional(definition), node)
    assert ids(bundle, "actions") == set()
    assert ids(bundle, "states") == {"waiting_for_host"}
    assert ids(bundle, "entities") == {"StagedChange", "ApprovalRecord", "Operator"}
    assert ids(bundle, "relations") == {"approved_by"}
    assert ids(bundle, "properties") == {"StagedChange.status", "ApprovalRecord.payload_digest"}
    assert bundle.diagnostics["required_definition_count"] == 7
    assert all("ApplyApprovedChange" not in canonical_json(row) for row in bundle.public.values())


def test_observed_variant_adds_ancestors_not_siblings(definition):
    bundle = build(
        without_optional(definition), one_node("START", "task_started", "state"), ("Variant",)
    )
    assert ids(bundle, "entities") == {"Variant", "SellableItem", "Listing"}
    assert not bundle.public["relations"] and not bundle.public["properties"]


def test_wide_relation_keeps_all_endpoints_and_property_keeps_owner(definition):
    state = next(s for s in definition["states"] if s["id"] == "task_started")
    state["semantic_refs"]["required"]["relations"] = ["belongs_to_merchant"]
    state["semantic_refs"]["required"]["properties"] = ["Observation.source_updated_at"]
    bundle = build(definition, one_node("START", "task_started", "state"))
    relation = bundle.public["relations"][0]
    assert set(relation["domain"] + relation["range"]) <= ids(bundle, "entities")
    assert "Observation" in ids(bundle, "entities")
    assert len(relation["domain"]) == 6


def test_duplicate_action_is_deduplicated_but_sources_preserved(definition):
    subgraph = one_node()
    subgraph["nodes"].append({"id": "SECOND_STAGE", "kind": "action", "action_ref": "StageRestock"})
    bundle = build(definition, subgraph)
    assert ids(bundle, "actions") == {"StageRestock"}
    trace = next(t for t in bundle.diagnostics["dependency_paths"] if t["id"] == "StageRestock")
    assert trace["seed_sources"] == ["PG:SECOND_STAGE", "PG:STAGE"]


def test_optional_groups_are_atomic_and_required_never_removed(definition):
    # A relation optional root pulls both its domain/range endpoints; they fit together or not at all.
    state = next(s for s in definition["states"] if s["id"] == "task_started")
    state["semantic_refs"]["optional"]["relations"] = ["variant_of"]
    bundle = build(definition, one_node("START", "task_started", "state"), max_definitions=3)
    assert ids(bundle, "states") == {"task_started"}
    assert not bundle.public["relations"] and not bundle.public["entities"]
    assert bundle.diagnostics["status"] == "partial_optional"
    assert bundle.diagnostics["omitted_optional_refs"][0]["id"] == "variant_of"


def test_required_definitions_promoted_independent_of_optional_order(definition):
    graph = one_node("READ", "ReadListing")
    graph["nodes"].append({"id": "CALC", "kind": "action", "action_ref": "CalculateRestockPlan"})
    bundle = build(definition, graph, ("Variant",), semantic_budget_bytes=16000)
    trace = next(t for t in bundle.diagnostics["dependency_paths"] if t["id"] == "Listing.stock")
    assert trace["required"]
    trace = next(t for t in bundle.diagnostics["dependency_paths"] if t["id"] == "Variant")
    assert trace["required"]


def test_shuffling_source_and_node_order_changes_neither_public_nor_hash(definition):
    graph = one_node()
    graph["nodes"].append({"id": "WAIT", "kind": "state", "state_ref": "waiting_for_host"})
    first = build(definition, graph, ("Variant",))
    for kind in ("actions", "states", "entities", "relations", "properties", "check_catalog"):
        definition[kind].reverse()
        for item in definition[kind]:
            for name in ("domain", "range", "checks", "allowed_origins"):
                if name in item:
                    item[name].reverse()
            for group in item.get("semantic_refs", {}).values():
                for refs in group.values():
                    refs.reverse()
    graph["nodes"].reverse()
    second = build(definition, graph, ("Variant", "Variant"))
    assert first.public == second.public and first.content_hash == second.content_hash


def test_unused_definitions_do_not_spread_but_changed_descriptions_change_hash(definition):
    original = build(definition)
    definition["entities"].append({"id": "Unrelated", "description": "Unused object."})
    assert build(definition).content_hash == original.content_hash
    next(e for e in definition["entities"] if e["id"] == "StagedChange")["description"] += (
        " Reviewed."
    )
    assert build(definition).content_hash != original.content_hash


@pytest.mark.parametrize(
    "limits,code",
    [
        ({"semantic_budget_bytes": 1}, "SEMANTIC_BUDGET_EXCEEDED"),
        ({"max_definitions": 1}, "SEMANTIC_BUDGET_EXCEEDED"),
        ({"max_dependency_depth": 1}, "SEMANTIC_DEPTH_EXCEEDED"),
    ],
)
def test_required_limit_failure_is_explicit(definition, limits, code):
    with pytest.raises(SemanticError, match=code):
        build(definition, **limits)


def test_budget_counts_actual_projected_utf8_bytes(definition):
    clean = without_optional(definition)
    required = build(clean)
    size = required.diagnostics["included_bytes"]
    assert size == len(canonical_json(required.public).encode("utf-8"))
    assert build(clean, semantic_budget_bytes=size).public == required.public
    with pytest.raises(SemanticError, match="SEMANTIC_BUDGET_EXCEEDED"):
        build(clean, semantic_budget_bytes=size - 1)


def test_no_io_no_mutation_no_private_implementation_fields(definition, monkeypatch):
    registry = SemanticRegistry(definition)
    graph = one_node()
    before = copy.deepcopy((definition, graph))

    def forbid(*args, **kwargs):
        raise AssertionError("Builder must perform no I/O")

    monkeypatch.setattr(socket, "socket", forbid)
    monkeypatch.setattr(Path, "read_text", forbid)
    monkeypatch.setattr(Path, "write_text", forbid)
    bundle = SemanticContextBuilder().build(registry=registry, subgraph=graph)
    assert (definition, graph) == before
    for text in (
        "implementation",
        "source_field_path",
        "semantic_refs",
        "task_id",
        "approved_change_ids",
    ):
        assert text not in canonical_json(bundle.public)
    bundle.public["actions"][0]["checks"].clear()
    assert registry.get_action("StageRestock")["checks"]


def test_unknown_or_malformed_seed_is_not_guessed(definition):
    for graph in [one_node(ref="NotKnown"), one_node(kind="unknown"), {"nodes": []}]:
        with pytest.raises(SemanticError):
            build(definition, graph)
    with pytest.raises(SemanticError):
        build(definition, observed=("unknown",))


# Upper-envelope preflight retains all branches; real predicate-sorted retrieval is tested in integration.
@pytest.mark.parametrize("hops", [0, 1, 2])
@pytest.mark.parametrize("observed", [(), ("SellableItem",), ("Variant",)])
@pytest.mark.parametrize(
    "node_id",
    [
        "START",
        "READ_ALERTS",
        "READ_LISTING",
        "READ_PENDING",
        "ASSESS",
        "CALCULATE",
        "STAGE",
        "WAIT_APPROVAL",
        "VERIFY",
        "RECONCILE",
        "NEED_INPUT",
        "REVIEW_EXISTING",
        "NO_ACTION",
        "SUCCESS",
        "DECLINED",
    ],
)
def test_every_node_hop_and_target_type_preflight(definition, node_id, hops, observed):
    graph = json.loads((ROOT / "knowledge/pg/inventory_restock.v1.json").read_text())
    nodes = {n["id"]: n for n in graph["nodes"]}
    seen, queue = set(), deque([(node_id, 0)])
    while queue:
        current, depth = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        if depth < hops:
            queue.extend((e["target"], depth + 1) for e in graph["edges"] if e["source"] == current)
    local = {"current_node": node_id, "nodes": [nodes[n] for n in sorted(seen)]}
    bundle = build(definition, local, observed, semantic_budget_bytes=16000)
    assert bundle.diagnostics["required_definition_count"] <= 64
    assert set(bundle.diagnostics["seed_action_refs"]) == {
        n["action_ref"] for n in local["nodes"] if "action_ref" in n
    }
    assert set(bundle.diagnostics["seed_state_refs"]) == {
        n["state_ref"] for n in local["nodes"] if "state_ref" in n
    }
    included = {
        (kind, item["id"])
        for kind in ("actions", "states", "entities", "relations", "properties", "checks")
        for item in bundle.public[kind]
    }
    assert included == {(t["kind"], t["id"]) for t in bundle.diagnostics["dependency_paths"]}
