"""Offline-only candidate edits, evidence gates and immutable knowledge releases."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .guidance import model_json
from .models import StrictModel, digest, uid
from .procedural import ProcedureGraph


class Operation(StrictModel):
    op: Literal["add_node", "remove_node", "add_edge", "remove_edge", "update_edge_attributes"]
    id: str
    value: dict = Field(default_factory=dict)


class CandidatePatch(StrictModel):
    base_version: str
    base_hash: str
    edit_id: str
    operations: list[Operation] = Field(max_length=20)
    rationale: str = Field(max_length=2000)
    training_evidence_ids: list[str] = Field(max_length=50)


def apply_patch(graph: ProcedureGraph, patch: CandidatePatch) -> ProcedureGraph:
    if patch.base_hash != graph.content_hash or patch.base_version != graph.definition["version"]:
        raise ValueError("Candidate base version/hash mismatch")
    candidate = copy.deepcopy(graph.definition)
    for operation in patch.operations:
        node_op = operation.op.endswith("node")
        key = "nodes" if node_op else "edges"
        items = candidate[key]
        existing = next((item for item in items if item["id"] == operation.id), None)
        if operation.op.startswith("add_"):
            if existing or operation.value.get("id") != operation.id:
                raise ValueError("Added ID must be new and match the operation")
            items.append(copy.deepcopy(operation.value))
        elif operation.op.startswith("remove_"):
            if not existing:
                raise ValueError("Removed ID does not exist")
            if node_op and any(
                operation.id in (e["source"], e["target"]) for e in candidate["edges"]
            ):
                raise ValueError("Remove incident edges explicitly before removing a node")
            items.remove(existing)
        else:
            if not existing:
                raise ValueError("Updated edge does not exist")
            if not set(operation.value) <= {
                "condition",
                "guidance",
                "pitfalls",
                "predicate_id",
                "priority",
                "evidence_requirements",
            }:
                raise ValueError("Candidate attempted an immutable attribute")
            existing.update(copy.deepcopy(operation.value))
    # Canonical content equality ignores proposed labels/version so equivalent edits deduplicate.
    candidate["nodes"].sort(key=lambda n: n["id"])
    candidate["edges"].sort(key=lambda e: e["id"])
    return ProcedureGraph(candidate, graph.schema, graph.ontology)


def validation_gate(
    baseline: dict, candidate: dict, *, max_token_ratio: float = 1.5
) -> tuple[bool, list[str]]:
    reasons = []
    if candidate.get("unmetered_calls", 0) or baseline.get("unmetered_calls", 0):
        reasons.append("missing_usage_evidence")
    for field in ("manifest_hash", "model", "environment_hash", "config_hash"):
        if not baseline.get(field) or baseline[field] != candidate.get(field):
            reasons.append(f"incomparable_{field}")
    if candidate.get("role") != "validation" or candidate.get("repetitions", 0) < 3:
        reasons.append("insufficient_independent_validation")
    if candidate.get("safety_violations", 1) != 0 or not candidate.get("safety_regression_passed"):
        reasons.append("safety_regression")
    if candidate.get("valid", 0) != candidate.get("submitted") or not candidate.get("valid"):
        reasons.append("infrastructure_or_missing_evidence")
    if candidate.get("success_rate", -1) < baseline.get("success_rate", 0):
        reasons.append("task_regression")
    for category, failures in candidate.get("critical_failures", {}).items():
        if failures > baseline.get("critical_failures", {}).get(category, 0):
            reasons.append(f"critical_regression:{category}")
    if (
        candidate.get("total_tokens", float("inf"))
        > baseline.get("total_tokens", 0) * max_token_ratio
    ):
        reasons.append("cost_limit")
    return not reasons, reasons


def validate_splits(root: Path, paths: list[Path]) -> None:
    groups: set[str] = set()
    case_ids: set[str] = set()
    for path in paths:
        manifest = json.loads(path.read_text())
        tasks = [json.loads((root / name).read_text()) for name in manifest["tasks"]]
        current_groups = {task["family_group"] for task in tasks}
        current_ids = {task["case_id"] for task in tasks}
        if not tasks or groups & current_groups or case_ids & current_ids:
            raise ValueError("Training/validation/test groups overlap or contain no tasks")
        groups.update(current_groups)
        case_ids.update(current_ids)


class EvolutionRunner:
    def __init__(self, directory: Path, graph: ProcedureGraph):
        self.directory, self.graph = directory, graph
        directory.mkdir(parents=True, exist_ok=True)

    def consider(
        self,
        raw: dict,
        *,
        baseline: dict | None = None,
        validation: dict | None = None,
        usage: dict | None = None,
    ) -> dict:
        record: dict[str, Any] = {
            "candidate_id": uid("candidate"),
            "patch": raw,
            "status": "rejected",
            "reasons": [],
        }
        if usage is not None:
            record["refiner_usage"] = usage
        try:
            patch = CandidatePatch.model_validate(raw)
            candidate = apply_patch(self.graph, patch)
            canonical = digest(
                {"nodes": candidate.definition["nodes"], "edges": candidate.definition["edges"]}
            )
            record["candidate_hash"] = candidate.content_hash
            record["canonical_hash"] = canonical
            history = self.history()
            base_canonical = digest(
                {
                    "nodes": sorted(self.graph.definition["nodes"], key=lambda x: x["id"]),
                    "edges": sorted(self.graph.definition["edges"], key=lambda x: x["id"]),
                }
            )
            if canonical == base_canonical:
                record.update(status="unchanged", reasons=["no_executable_changes"])
            elif any(item.get("canonical_hash") == canonical for item in history):
                record["reasons"] = ["equivalent_candidate"]
            elif baseline is None or validation is None:
                record.update(status="candidate", reasons=["awaiting_independent_validation"])
            else:
                accepted, reasons = validation_gate(baseline, validation)
                record.update(
                    status="accepted" if accepted else "rejected",
                    reasons=reasons,
                    validation_hash=digest(validation),
                    baseline_hash=digest(baseline),
                )
            if record["status"] in {"candidate", "accepted"}:
                path = self.directory / f"{record['candidate_id']}.graph.json"
                path.write_text(
                    json.dumps(candidate.definition, ensure_ascii=False, indent=2) + "\n"
                )
                record["graph_path"] = str(path)
        except (ValueError, KeyError, TypeError) as error:
            record["reasons"] = [f"structure_or_semantic_error:{type(error).__name__}"]
        except Exception as error:
            record["reasons"] = [f"validation_error:{type(error).__name__}"]
        with (self.directory / "history.jsonl").open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def history(self) -> list[dict]:
        path = self.directory / "history.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    async def propose(self, client, model: str, training: dict, prompt: str) -> dict:
        if training.get("role") != "training":
            raise ValueError("Only training diagnostics may be passed to the refiner")
        rejection_memory = [
            {"candidate_hash": r.get("candidate_hash"), "reasons": r["reasons"]}
            for r in self.history()[-20:]
            if r["status"] == "rejected"
        ]
        proposal, usage = await model_json(
            client,
            model=model,
            system=prompt
            + "\nReturn ONLY a JSON object matching this exact schema. No extra fields. Empty operations are allowed.\n"
            + json.dumps(CandidatePatch.model_json_schema()),
            data={
                "graph": self.graph.definition,
                "base_hash": self.graph.content_hash,
                "base_version": self.graph.definition["version"],
                "allowed_actions": list(self.graph.ontology.actions),
                "training": training,
                "rejection_memory": rejection_memory,
            },
            max_tokens=2000,
            timeout=60,
        )
        known = {row["evidence_id"] for row in training.get("evidence", [])}
        if not set(proposal.get("training_evidence_ids", [])) <= known:
            raise ValueError("Refiner references unknown training evidence")
        return self.consider(proposal, usage=usage)


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_release(root: Path, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest.get("status") != "published"
        or not manifest.get("approved_by")
        or not manifest.get("validation_run_id")
    ):
        raise ValueError("Release is not published with approval and validation")
    if not manifest.get("content_hashes") or not manifest.get("runtime_commit"):
        raise ValueError("Incomplete release provenance")
    for name, expected in manifest["content_hashes"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or sha_file(path) != expected:
            raise ValueError(f"Release hash mismatch: {name}")
    return manifest


def publish(
    root: Path,
    *,
    graph: ProcedureGraph,
    config: Any,
    approved_by: str,
    validation_path: Path,
    initial: bool = False,
) -> dict:
    if config.effective_semantic_mode == "closure":
        raise ValueError(
            "Semantic extensions require publish-semantic; --initial cannot enable closure"
        )
    validation = json.loads(validation_path.read_text())
    if not approved_by.strip():
        raise ValueError("A release requires an explicit reviewer identity")
    if initial:
        if (
            not validation.get("safety_regression_passed")
            or validation.get("graph_hash") != graph.content_hash
        ):
            raise ValueError(
                "The initial manual graph requires matching safety regression evidence"
            )
    else:
        accepted, _ = validation_gate(
            validation.get("baseline", {}), validation.get("candidate", {})
        )
        if (
            not accepted
            or not validation.get("accepted")
            or validation.get("graph_hash") != graph.content_hash
        ):
            raise ValueError("An evolved graph requires accepted independent validation")
    release_id = uid("retail")
    directory = root / "knowledge/releases" / release_id
    directory.mkdir(parents=True, exist_ok=False)
    paths = [
        config.ontology_path,
        config.pg_path,
        config.predicates_path,
        config.schema_path,
        "knowledge/prompts/guidance.txt",
        "knowledge/prompts/solver.txt",
        "knowledge/prompts/refiner.txt",
    ]
    hashes = {}
    knowledge_paths = {}
    for source in paths:
        destination = directory / Path(source).name
        shutil.copyfile(root / source, destination)
        hashes[str(destination.relative_to(root))] = sha_file(destination)
        for field in ("ontology_path", "pg_path", "predicates_path", "schema_path"):
            if getattr(config, field) == source:
                knowledge_paths[field] = str(destination.relative_to(root))
    evidence = directory / "validation.json"
    shutil.copyfile(validation_path, evidence)
    hashes[str(evidence.relative_to(root))] = sha_file(evidence)
    manifest = {
        "release_id": release_id,
        "status": "published",
        "approved_by": approved_by,
        "validation_run_id": validation.get("run_id", digest(validation)),
        "runtime_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "runtime_source_hash": digest(
            {
                str(p.relative_to(root)): sha_file(p)
                for p in sorted((root / "commerce-reasoning/commerce_reasoning").glob("*.py"))
            }
        ),
        "graph_hash": graph.content_hash,
        "ontology_hash": graph.ontology.content_hash,
        "content_hashes": hashes,
        "knowledge_paths": knowledge_paths,
        "initial_manual_release": initial,
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    activate(root, manifest_path)
    return manifest


def activate(root: Path, manifest_path: Path) -> None:
    manifest = verify_release(root, manifest_path)
    active = root / "knowledge/releases/active.json"
    temporary = active.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    os.replace(temporary, active)
