"""Synthetic publication-mechanism tests; no record is real evaluation evidence."""

import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from commerce_common.testing import FakeClient, FakeCreateClient, text_message
from commerce_reasoning.config import ReasoningConfig
from commerce_reasoning.execution import SOLVER_NOTICE, MerchantExecutionService
from commerce_reasoning.guidance import GUIDANCE_SYSTEM
from commerce_reasoning.procedural import load_knowledge
from commerce_reasoning.semantic_audit import ORACLE_PATH
from commerce_reasoning.semantic_evaluation import comparison_fields
from commerce_reasoning.semantic_models import SemanticError
from commerce_reasoning.semantic_release import (
    INTEGRATION_SOURCES,
    SOURCE_ROOTS,
    load_effective_prompts,
    publish_semantic,
    resolve_knowledge,
    semantic_identity,
    source_identity,
    validate_semantic_evidence,
)
from commerce_reasoning.storage import Store
from merchant_agent import MerchantAgentConfig
from merchant_agent_runtime import MerchantAgent

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def working(tmp_path):
    shutil.copytree(ROOT / "knowledge", tmp_path / "knowledge")
    for directory in SOURCE_ROOTS:
        shutil.copytree(ROOT / directory, tmp_path / directory)
    for name in (*INTEGRATION_SOURCES, "requirements.txt", "requirements-dev.txt", ORACLE_PATH):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    config = ReasoningConfig.from_file(ROOT / "configs/experiments/p-closure.yaml")
    registry, graph = load_knowledge(tmp_path, config)
    return tmp_path, config, registry, graph


def synthetic_evidence(
    root, config, registry, graph, *, guidance=GUIDANCE_SYSTEM, solver=SOLVER_NOTICE
):
    from commerce_reasoning.semantic_release import effective_prompts

    # These dictionaries exercise gate contracts, not a claim of model improvement.
    reports = []
    for mode in ("legacy", "closure"):
        cfg = config.model_copy(update={"semantic_context_mode": mode})
        service = SimpleNamespace(
            config=cfg,
            loaded_config=cfg,
            registry=registry,
            graph=graph,
            guidance=SimpleNamespace(system=guidance),
            solver_notice=solver,
            effective_prompt_identity=effective_prompts(guidance, solver),
        )
        agent_config = MerchantAgentConfig(model="synthetic-test-model", enable_analysis=False)
        reports.append(
            {
                **comparison_fields(root, service, agent_config),
                "model": agent_config.model,
                "variant": "P",
                "role": "validation",
                "repetitions": 3,
                "manifest_hash": "synthetic-manifest",
                "environment_hash": "synthetic-environment",
                "submitted": 3,
                "valid": 3,
                "successes": 3,
                "total_tokens": 100,
                "unmetered_calls": 0,
                "safety_violations": 0,
                "critical_failures": {"stock": 0, "host_authorization": 0},
            }
        )
    identity = semantic_identity(root, graph, config, guidance=guidance, solver=solver)
    return {
        "kind": "semantic_extension",
        "run_id": "synthetic-unit-test-not-live-evidence",
        "identity": identity,
        "accepted": True,
        "baseline": reports[0],
        "candidate": reports[1],
        "semantic_tests": {
            "passed": True,
            "identity": identity,
            "report_hash": "synthetic-semantic-report",
            "command": ["synthetic"],
        },
        "execution_safety": {
            "passed": True,
            "identity": identity,
            "report_hash": "synthetic-safety-report",
            "command": ["synthetic"],
        },
    }


def publish_fixture(working, *, guidance=GUIDANCE_SYSTEM, solver=SOLVER_NOTICE):
    root, config, registry, graph = working
    evidence = synthetic_evidence(root, config, registry, graph, guidance=guidance, solver=solver)
    path = root / "synthetic-evidence.json"
    path.write_text(json.dumps(evidence))
    return publish_semantic(
        root,
        graph=graph,
        config=config,
        approved_by="synthetic-test-reviewer",
        validation_path=path,
        guidance=guidance,
        solver=solver,
    )


def test_old_release_is_readable_only_in_legacy_without_working_fallback(working):
    root, config, _, _ = working
    old = config.model_copy(update={"semantic_context_mode": "legacy"})
    resolved, manifest = resolve_knowledge(root, old, source="published")
    assert "/releases/" in resolved.ontology_path
    registry, _ = load_knowledge(root, resolved)
    assert registry.semantic_registry is None
    assert load_effective_prompts(
        root, manifest, guidance=GUIDANCE_SYSTEM, solver=SOLVER_NOTICE
    ) == (GUIDANCE_SYSTEM, SOLVER_NOTICE)
    with pytest.raises(SemanticError, match="closure_requires_semantic_release"):
        resolve_knowledge(root, config, source="published")


def test_schema_and_prompts_are_loaded_from_an_immutable_semantic_snapshot(working):
    root, config, _, _ = working
    guide, solver = (
        GUIDANCE_SYSTEM + "\nSnapshot guide marker.",
        SOLVER_NOTICE + "\nSnapshot solver marker.",
    )
    manifest = publish_fixture(working, guidance=guide, solver=solver)
    resolved, loaded = resolve_knowledge(root, config, source="published")
    assert loaded["release_kind"] == "semantic_extension"
    assert resolved.semantic_schema_path in manifest["content_hashes"]
    assert load_effective_prompts(root, loaded, guidance="ignored", solver="ignored") == (
        guide,
        solver,
    )
    # A change to a mutable authoring path does not replace a published snapshot.
    (root / config.ontology_path).write_text("invalid working content")
    registry, _ = load_knowledge(root, resolved)
    assert registry.get_action("StageRestock")["semantic_refs"]


async def test_actual_fake_model_request_uses_published_effective_prompt(working):
    root, config, _, _ = working
    guide, solver = (
        GUIDANCE_SYSTEM + "\nActual snapshot guide.",
        SOLVER_NOTICE + "\nActual snapshot solver.",
    )
    publish_fixture(working, guidance=guide, solver=solver)
    store = Store(":memory:")
    service = MerchantExecutionService(backend=object(), root=root, config=config, store=store)
    client = FakeCreateClient([text_message('{"immediate_goal":"Wait"}')])
    try:
        await service.guidance.build(
            client, "fake", {"enabled_actions": [], "edge_ids": [], "evidence_ids": []}, config
        )
        assert client.calls[0]["system"] == guide
        agent = MerchantAgent(
            backend=object(),
            config=MerchantAgentConfig(enable_analysis=False),
            client=FakeClient([]),
            execution_service=service,
        )
        assert agent._static_system.endswith(solver)
    finally:
        store.close()


def test_schema_prompt_and_source_tampering_are_rejected(working):
    root, config, _, _ = working
    manifest = publish_fixture(working)
    schema = root / manifest["knowledge_paths"]["semantic_schema_path"]
    original = schema.read_bytes()
    schema.write_text("{}")
    with pytest.raises(ValueError):
        resolve_knowledge(root, config, source="published")
    schema.write_bytes(original)
    prompt = root / manifest["effective_prompt_paths"]["guidance"]
    prompt.write_text("tampered")
    with pytest.raises(ValueError):
        resolve_knowledge(root, config, source="published")
    prompt.write_text(GUIDANCE_SYSTEM)
    nested = root / SOURCE_ROOTS[0] / "nested"
    nested.mkdir()
    (nested / "changed.py").write_text("NEW_SOURCE = True\n")
    with pytest.raises(SemanticError, match="runtime_source_hash"):
        resolve_knowledge(root, config, source="published")


def test_source_identity_covers_nested_and_integration_code(working):
    root, _, _, _ = working
    identity = source_identity(root)
    assert set(INTEGRATION_SOURCES) <= identity["files"].keys()
    nested = root / SOURCE_ROOTS[0] / "new"
    nested.mkdir()
    (nested / "logic.py").write_text("VALUE = 1\n")
    assert source_identity(root)["source_hash"] != identity["source_hash"]


@pytest.mark.parametrize("field", ["semantic_tests", "execution_safety", "candidate", "identity"])
def test_legacy_or_incomplete_evidence_cannot_publish(working, field):
    root, config, registry, graph = working
    evidence = synthetic_evidence(root, config, registry, graph)
    broken = copy.deepcopy(evidence)
    broken.pop(field)
    with pytest.raises((SemanticError, ValueError)):
        validate_semantic_evidence(broken, evidence["identity"])
    old_active = (root / "knowledge/releases/active.json").read_bytes()
    path = root / "bad-evidence.json"
    path.write_text(json.dumps(broken))
    with pytest.raises((SemanticError, ValueError)):
        publish_semantic(
            root,
            graph=graph,
            config=config,
            approved_by="reviewer",
            validation_path=path,
            guidance=GUIDANCE_SYSTEM,
            solver=SOLVER_NOTICE,
        )
    assert (root / "knowledge/releases/active.json").read_bytes() == old_active


def test_initial_switch_cannot_bypass_semantic_gate(working):
    from commerce_reasoning.evolution import publish

    root, config, _, graph = working
    with pytest.raises(ValueError, match="publish-semantic"):
        publish(
            root,
            graph=graph,
            config=config,
            approved_by="reviewer",
            validation_path=root / "missing.json",
            initial=True,
        )


def test_rollback_requires_a_compatible_mode_and_never_rewrites_knowledge(working):
    from commerce_reasoning.evolution import activate

    root, config, _, _ = working
    old = json.loads((root / "knowledge/releases/active.json").read_text())
    old_path = root / "knowledge/releases" / old["release_id"] / "manifest.json"
    old_bytes = old_path.read_bytes()
    publish_fixture(working)
    activate(root, old_path)
    assert old_path.read_bytes() == old_bytes
    resolved, _ = resolve_knowledge(
        root, config.model_copy(update={"semantic_context_mode": "legacy"}), source="published"
    )
    assert "/releases/" in resolved.ontology_path
    with pytest.raises(SemanticError, match="closure_requires_semantic_release"):
        resolve_knowledge(root, config, source="published")
