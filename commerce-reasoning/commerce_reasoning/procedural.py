"""Validated immutable graphs, three-valued predicates and bounded retrieval."""

import copy
import json
from collections import deque
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from .models import TaskRecord, digest
from .ontology import OntologyRegistry

PREDICATES = frozenset(
    {
        "target_missing",
        "has_target",
        "no_alerts_for_check_only",
        "has_valid_listing",
        "target_needs_clarification",
        "pending_snapshot_observed",
        "pending_present",
        "pending_absent",
        "ready_to_calculate",
        "needs_data",
        "positive_plan",
        "zero_plan",
        "plan_unavailable",
        "staged_ok",
        "stage_stale_retry_allowed",
        "stage_conflict",
        "host_applied",
        "host_discarded",
        "apply_unknown",
        "verified",
        "verification_failed",
        "reconciliation_ready",
    }
)


def predicate(name: str, context: dict) -> bool | None:
    task, view = context["task"], context["view"]
    plan, last = context.get("plan"), context.get("last", {})
    valid = bool(view.get("listing") and view["listing"]["kind"] != "ProductFamily")
    observations = view.get("observations", {})
    inputs = all(
        observations.get(f, {}).get("value_status") == "known" for f in ("stock", "sales_last_30d")
    )
    pending = view.get("pending_present")
    plan_valid = bool(plan and plan["status"] == "valid")
    values = {
        "target_missing": task.target is None,
        "has_target": task.target is not None,
        "no_alerts_for_check_only": (
            context["alerts"]["count"] == 0
            if context.get("alerts", {}).get("complete") and task.intent == "check_only"
            else None
        ),
        "has_valid_listing": valid if view.get("listing") else None,
        "target_needs_clarification": bool(view.get("listing") and not valid)
        or "target" in task.unknowns,
        "pending_snapshot_observed": bool(view.get("pending")),
        "pending_present": pending,
        "pending_absent": not pending if pending is not None else None,
        "ready_to_calculate": (valid and inputs and task.target_days is not None and not pending)
        if pending is not None
        else None,
        "needs_data": bool(task.unknowns) or not inputs or pending is None,
        "positive_plan": plan["quantity"] > 0 if plan_valid else None,
        "zero_plan": plan["quantity"] == 0 if plan_valid else None,
        "plan_unavailable": last.get("error_code")
        in {
            "MISSING_SALES_HISTORY",
            "GUARDRAIL_BLOCKED",
            "STALE_OBSERVATION",
            "MISSING_TASK_INPUT",
        },
        "staged_ok": task.phase == "WAIT_APPROVAL",
        "stage_stale_retry_allowed": last.get("error_code") == "STALE_PLAN"
        and task.recovery_reads < context.get("max_recovery_reads", 1),
        "stage_conflict": last.get("error_code") == "PENDING_CHANGE_CONFLICT",
        "host_applied": task.phase in {"VERIFY", "SUCCESS"} and task.host_outcome == "applied",
        "host_discarded": task.phase == "DECLINED" and task.host_outcome == "discarded",
        "apply_unknown": task.phase == "RECONCILE",
        "verified": task.phase == "SUCCESS",
        "verification_failed": last.get("error_code") == "EFFECT_NOT_VERIFIED",
        "reconciliation_ready": context.get("receipt_known", False),
    }
    if name not in PREDICATES:
        raise ValueError(f"Unknown predicate: {name}")
    return values[name]


class ProcedureGraph:
    def __init__(self, definition: dict, schema: dict, ontology: OntologyRegistry):
        jsonschema.validate(definition, schema)
        self.definition = copy.deepcopy(definition)
        self.ontology, self.schema = ontology, schema
        self.nodes = {node["id"]: node for node in definition["nodes"]}
        self.edges = {edge["id"]: edge for edge in definition["edges"]}
        if len(self.nodes) != len(definition["nodes"]) or len(self.edges) != len(
            definition["edges"]
        ):
            raise ValueError("Duplicate node or edge IDs")
        if definition["ontology_version"] != ontology.definition["version"]:
            raise ValueError("Incompatible ontology version")
        for node in self.nodes.values():
            required_ref = "action_ref" if node["kind"] == "action" else "state_ref"
            if required_ref not in node:
                raise ValueError("Node kind does not match its action/state reference")
            if node.get("action_ref") and node["action_ref"] not in ontology.actions:
                raise ValueError("Unknown action")
            if node.get("state_ref") and node["state_ref"] not in ontology.states:
                raise ValueError("Unknown state")
        for edge in self.edges.values():
            if edge["source"] not in self.nodes or edge["target"] not in self.nodes:
                raise ValueError("Unknown edge endpoint")
            if edge.get("predicate_id") not in PREDICATES:
                raise ValueError("Unknown predicate")
        entry = definition["entry_node"]
        if entry not in self.nodes:
            raise ValueError("Unknown entry")
        if self.reachable(entry) != set(self.nodes):
            raise ValueError("Unreachable nodes")
        terminals = {node["id"] for node in self.nodes.values() if node["kind"] == "terminal"}
        if not terminals or any(not (self.reachable(node) & terminals) for node in self.nodes):
            raise ValueError("A node or loop has no terminal exit")
        self.content_hash = digest(definition)

    @classmethod
    def load(cls, graph_path: Path, schema_path: Path, ontology: OntologyRegistry):
        return cls(
            json.loads(graph_path.read_text()), json.loads(schema_path.read_text()), ontology
        )

    def reachable(self, start: str) -> set[str]:
        visited, queue = set(), [start]
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(edge["target"] for edge in self.edges.values() if edge["source"] == node)
        return visited

    def validate_enabled(self, enabled_tools: set[str]) -> None:
        missing = {
            self.ontology.actions[node["action_ref"]]["tool_binding"]
            for node in self.nodes.values()
            if node.get("action_ref")
        } - enabled_tools
        if missing:
            raise ValueError(f"Graph uses disabled tools: {sorted(missing)}")


class ProcedureLocator:
    @staticmethod
    def locate(task: TaskRecord, graph: ProcedureGraph) -> tuple[str, bool]:
        # phase is written exclusively by the executor's typed results and host events.
        if task.phase in graph.nodes:
            return task.phase, False
        references = {
            "START": "task_started",
            "READ_ALERTS": "ReadInventoryAlerts",
            "READ_LISTING": "ReadListing",
            "READ_PENDING": "ReadPendingChanges",
            "ASSESS": "assessment_ready",
            "CALCULATE": "CalculateRestockPlan",
            "STAGE": "StageRestock",
            "WAIT_APPROVAL": "waiting_for_host",
            "VERIFY": "VerifyAppliedChange",
            "RECONCILE": "outcome_unknown",
            "NEED_INPUT": "needs_input",
            "REVIEW_EXISTING": "review_existing",
            "NO_ACTION": "no_action",
            "SUCCESS": "success",
            "DECLINED": "declined",
        }
        reference = references.get(task.phase)
        matches = sorted(
            node["id"]
            for node in graph.nodes.values()
            if reference and reference in (node.get("action_ref"), node.get("state_ref"))
        )
        return (matches[0], False) if matches else (graph.definition["entry_node"], True)


class SubgraphRetriever:
    def retrieve(
        self,
        graph: ProcedureGraph,
        node: str,
        context: dict,
        *,
        hops: int = 2,
        budget: int = 2000,
        full: bool = False,
    ) -> dict:
        queue, visited, selected = deque([(node, 0)]), set(), []
        while queue:
            source, depth = queue.popleft()
            if source in visited:
                continue
            visited.add(source)
            if depth >= hops and not full:
                continue
            edges = []
            for edge in graph.edges.values():
                if edge["source"] == source:
                    truth = predicate(edge["predicate_id"], context)
                    edges.append(
                        edge
                        | {"predicate_status": "unknown" if truth is None else str(truth).lower()}
                    )
            edges.sort(
                key=lambda e: (
                    {"true": 0, "unknown": 1, "false": 2}[e["predicate_status"]],
                    -e.get("priority", 0),
                    e["id"],
                )
            )
            selected.extend(edges)
            queue.extend((edge["target"], depth + 1) for edge in edges)
        result = {
            "current_node": node,
            "nodes": [graph.nodes[node]],
            "edges": [],
            "omitted_count": 0,
        }
        # Conservative UTF-8 byte budget, never presented as an exact tokenizer count.
        for edge in selected:
            if edge["source"] not in {n["id"] for n in result["nodes"]}:
                result["omitted_count"] += 1
                continue
            candidate = copy.deepcopy(result)
            candidate["edges"].append(edge)
            for endpoint in (edge["source"], edge["target"]):
                if endpoint not in {n["id"] for n in candidate["nodes"]}:
                    candidate["nodes"].append(graph.nodes[endpoint])
            if len(json.dumps(candidate, ensure_ascii=False).encode()) <= budget:
                result = candidate
            else:
                result["omitted_count"] += 1
        if selected and not result["edges"]:
            raise ValueError("Context budget cannot preserve the required graph edges")
        if full and result["omitted_count"]:
            raise ValueError("Full-graph locator fallback exceeds the context budget")
        return result


def load_knowledge(root: Path, config: Any) -> tuple[OntologyRegistry, ProcedureGraph]:
    config = config.validate_effective()
    ontology = OntologyRegistry(root / config.ontology_path)
    if config.effective_semantic_mode == "closure":
        ontology.validate_semantic_refs(root / config.semantic_schema_path)
    predicates = yaml.safe_load((root / config.predicates_path).read_text())
    if {p["id"] for p in predicates["predicates"]} != PREDICATES:
        raise ValueError("Predicate registry does not match its implementations")
    graph = ProcedureGraph.load(root / config.pg_path, root / config.schema_path, ontology)
    return ontology, graph
