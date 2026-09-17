"""Explicit knowledge provenance and evidence-gated semantic releases.

Hash checks detect incompatible content; reviewer labels are not an authentication system.
No function here authorizes or reverses a business operation.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .config import ReasoningConfig
from .semantic_models import BUILDER_VERSION, SemanticError, content_hash

SOURCE_ROOTS = (
    "commerce-reasoning/commerce_reasoning",
    "merchant-agent/core/merchant_agent",
    "commerce-common/commerce_common",
)
INTEGRATION_SOURCES = (
    "merchant-agent/runtime-messages-api/merchant_agent_runtime/orchestrator.py",
    "examples/demo_common/merchant.py",
    "examples/retail/api/reasoning_backend.py",
    "commerce-common/commerce_common/turn.py",
)
PATH_FIELDS = ("ontology_path", "pg_path", "predicates_path", "schema_path", "semantic_schema_path")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "path_scope")
    return path


def source_identity(root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            str(path.relative_to(root))
            for directory in SOURCE_ROOTS
            for path in (root / directory).rglob("*.py")
        }
        | {
            name
            for name in (*INTEGRATION_SOURCES, "requirements.txt", "requirements-dev.txt")
            if (root / name).is_file()
        }
    )
    files = {name: sha_bytes(safe_path(root, name).read_bytes()) for name in paths}
    if not files:
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "source_manifest")
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.check_output(
            ["git", "diff", "--no-ext-diff", "HEAD", "--", *paths],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, b""
    return {
        "source_hash": content_hash(files),
        "files": files,
        "commit": commit,
        "dirty_diff_hash": sha_bytes(dirty) if dirty else None,
    }


def effective_prompts(guidance: str, solver: str) -> dict[str, Any]:
    hashes = {"guidance": sha_bytes(guidance.encode()), "solver": sha_bytes(solver.encode())}
    return {"hashes": hashes, "combined_hash": content_hash(hashes)}


def behavioral_config(config: ReasoningConfig) -> dict:
    # Storage locations and debug visibility do not define business/model behavior.
    result = config.validate_effective().model_dump()
    for key in (*PATH_FIELDS, "release_manifest", "audit_store", "debug_enabled"):
        result.pop(key, None)
    return result


def resolve_knowledge(
    root: Path, config: ReasoningConfig, *, source: str
) -> tuple[ReasoningConfig, dict | None]:
    config = config.validate_effective()
    if source == "working":
        return config, None
    if source != "published":
        raise ValueError("knowledge_source must be working or published")
    from .evolution import verify_release

    manifest = verify_release(root, safe_path(root, config.release_manifest))
    paths = manifest.get("knowledge_paths", {})
    if not set(paths) <= set(PATH_FIELDS):
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "knowledge_paths")
    mandatory = set(PATH_FIELDS[:4])
    semantic_release = manifest.get("release_kind") == "semantic_extension"
    if config.effective_semantic_mode == "closure" and not semantic_release:
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "closure_requires_semantic_release")
    if semantic_release:
        mandatory.add("semantic_schema_path")
        if manifest.get("builder_version") != BUILDER_VERSION:
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "builder_version")
        if manifest.get("runtime_source_hash") != source_identity(root)["source_hash"]:
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "runtime_source_hash")
        # Both reviewed modes may consume the same snapshot; all other behavior stays fixed.
        expected = dict(manifest.get("behavioral_config", {}))
        actual = behavioral_config(config)
        expected.pop("semantic_context_mode", None)
        actual.pop("semantic_context_mode", None)
        if expected != actual:
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "behavioral_config")
    if not mandatory <= paths.keys():
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "missing_knowledge_paths")
    for path in paths.values():
        if path not in manifest["content_hashes"]:
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "unhashed_knowledge_path")
        safe_path(root, path)
    resolved = config.model_copy(update=paths).validate_effective()
    return resolved, manifest


def validate_loaded_knowledge(registry: Any, graph: Any, manifest: dict | None) -> None:
    if manifest is None:
        return
    if (
        manifest.get("graph_hash") != graph.content_hash
        or manifest.get("ontology_hash") != registry.content_hash
    ):
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "loaded_knowledge_hash")
    if manifest.get("release_kind") == "semantic_extension":
        semantic = registry.validate_semantic_refs()
        if manifest.get("semantic_schema_hash") != semantic.schema_hash:
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "semantic_schema_hash")


def load_effective_prompts(
    root: Path, manifest: dict | None, *, guidance: str, solver: str
) -> tuple[str, str]:
    if not manifest or manifest.get("release_kind") != "semantic_extension":
        return guidance, solver
    paths = manifest.get("effective_prompt_paths", {})
    if set(paths) != {"guidance", "solver"}:
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "effective_prompt_paths")
    values = {}
    for role, name in paths.items():
        if name not in manifest["content_hashes"]:
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "unhashed_prompt_path")
        path = safe_path(root, name)
        if path.stat().st_size > 100_000:
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "prompt_size")
        raw = path.read_bytes()
        if sha_bytes(raw) != manifest["content_hashes"][name]:
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "prompt_hash")
        values[role] = raw.decode("utf-8")
    actual = effective_prompts(values["guidance"], values["solver"])
    if actual["combined_hash"] != manifest.get("effective_prompt_hash"):
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "effective_prompt_hash")
    return values["guidance"], values["solver"]


def semantic_identity(
    root: Path, graph: Any, config: ReasoningConfig, *, guidance: str, solver: str
) -> dict:
    registry = graph.ontology.validate_semantic_refs(root / config.semantic_schema_path)
    return {
        "graph_hash": graph.content_hash,
        "ontology_hash": graph.ontology.content_hash,
        "semantic_schema_hash": registry.schema_hash,
        "builder_version": BUILDER_VERSION,
        "runtime_source_hash": source_identity(root)["source_hash"],
        "effective_prompt_hash": effective_prompts(guidance, solver)["combined_hash"],
        "behavioral_config_hash": content_hash(behavioral_config(config)),
    }


def validate_semantic_evidence(evidence: dict, identity: dict) -> None:
    from .semantic_evaluation import compare_semantic_reports

    if evidence.get("kind") != "semantic_extension" or not evidence.get("run_id"):
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "evidence_kind")
    if evidence.get("identity") != identity:
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "evidence_identity")
    for name in ("semantic_tests", "execution_safety"):
        record = evidence.get(name, {})
        if (
            record.get("passed") is not True
            or record.get("identity") != identity
            or not record.get("report_hash")
            or not record.get("command")
        ):
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", name)
    baseline, candidate = evidence.get("baseline", {}), evidence.get("candidate", {})
    accepted, reasons = compare_semantic_reports(baseline, candidate)
    if not accepted:
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "comparison:" + ",".join(reasons))
    if candidate.get("semantic_identity") != identity or evidence.get("accepted") is not True:
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "candidate_identity")
    if candidate.get("role") != "validation" or candidate.get("repetitions", 0) < 3:
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "independent_validation")


def publish_semantic(
    root: Path,
    *,
    graph: Any,
    config: ReasoningConfig,
    approved_by: str,
    validation_path: Path,
    guidance: str,
    solver: str,
) -> dict:
    """A separate manually reviewed migration path, never an initial-graph bypass."""
    from .evolution import activate
    from .models import uid

    config = config.validate_effective()
    if config.effective_semantic_mode != "closure" or not approved_by.strip():
        raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "reviewed_closure_required")
    identity = semantic_identity(root, graph, config, guidance=guidance, solver=solver)
    evidence = json.loads(validation_path.read_text())
    validate_semantic_evidence(evidence, identity)
    release_id = uid("retail-semantic")
    directory = root / "knowledge/releases" / release_id
    directory.mkdir(parents=True, exist_ok=False)
    hashes, paths, prompt_paths = {}, {}, {}
    # Work in a fresh directory; no old release files are overwritten.
    for field in PATH_FIELDS:
        source = safe_path(root, getattr(config, field))
        destination = directory / field / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = source.read_bytes()
        destination.write_bytes(raw)
        relative = str(destination.relative_to(root))
        hashes[relative], paths[field] = sha_bytes(raw), relative
    for role, text in (("guidance", guidance), ("solver", solver)):
        path = directory / f"{role}.effective.txt"
        path.write_bytes(text.encode())
        relative = str(path.relative_to(root))
        hashes[relative], prompt_paths[role] = sha_bytes(text.encode()), relative
    validation = directory / "validation.json"
    raw = validation_path.read_bytes()
    validation.write_bytes(raw)
    hashes[str(validation.relative_to(root))] = sha_bytes(raw)
    source = source_identity(root)
    manifest = {
        "release_id": release_id,
        "release_kind": "semantic_extension",
        "status": "published",
        "approved_by": approved_by,
        "validation_run_id": evidence["run_id"],
        "runtime_commit": source["commit"] or "source-archive",
        "source_identity": source,
        **identity,
        "content_hashes": hashes,
        "knowledge_paths": paths,
        "effective_prompt_paths": prompt_paths,
        "behavioral_config": behavioral_config(config),
        "initial_manual_release": False,
    }
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    # Validate exactly the source that will be loaded before touching the active pointer.
    resolve_knowledge(
        root,
        config.model_copy(update={"release_manifest": str(path.relative_to(root))}),
        source="published",
    )
    load_effective_prompts(root, manifest, guidance=guidance, solver=solver)
    activate(root, path)
    return manifest
