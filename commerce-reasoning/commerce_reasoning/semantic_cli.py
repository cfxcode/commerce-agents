"""Offline semantic inspection, regression evidence and explicit reviewed publication."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .guidance import GUIDANCE_SYSTEM
from .models import TaskRecord, uid
from .semantic_context import SemanticContextBuilder
from .semantic_evaluation import compare_semantic_reports
from .semantic_models import BUILDER_VERSION, SemanticDefinitionLimits, SemanticError, content_hash
from .semantic_release import load_effective_prompts, publish_semantic, semantic_identity

COMMANDS = {
    "inspect-semantics",
    "preflight-semantics",
    "verify-semantics",
    "compare-semantics",
    "publish-semantic",
}


def write_json(root: Path, destination: Path, payload: dict) -> None:
    target = root / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def inspect(root, config, registry, graph, fixture, node, hops):
    from .procedural import SubgraphRetriever

    data = json.loads(fixture.read_text())
    task = TaskRecord.model_validate(data["task"])
    if node not in graph.nodes:
        raise SemanticError("SEMANTIC_REF_MISSING", "node")
    view = data["view"]
    if not isinstance(view, dict):
        raise SemanticError("SEMANTIC_SCHEMA_INVALID", "fixture.view")
    context = {
        "task": task,
        "view": view,
        "plan": data.get("plan"),
        "last": data.get("last", {}),
        "alerts": data.get("alerts", {}),
        "max_recovery_reads": config.max_recovery_reads,
    }
    subgraph = SubgraphRetriever().retrieve(
        graph, node, context, hops=hops, budget=config.pg_budget_bytes
    )
    kind = view.get("listing", {}).get("kind") if view.get("listing") else None
    bundle = SemanticContextBuilder().build(
        registry=registry,
        subgraph=subgraph,
        observed_type_ids=(kind,) if kind and kind != "unknown" else (),
        limits=SemanticDefinitionLimits(
            max_definitions=config.semantic_max_definitions,
            max_dependency_depth=config.semantic_max_dependency_depth,
            semantic_budget_bytes=config.semantic_budget_bytes,
        ),
    )
    return {
        "public": bundle.public,
        "diagnostics": bundle.diagnostics,
        "content_hash": bundle.content_hash,
        "subgraph": subgraph,
        "model_requested": False,
        "business_writes": False,
    }


def preflight(config, registry, graph):
    from .procedural import SubgraphRetriever

    task_template = {
        "merchant_id": "fixture",
        "operator": "fixture",
        "session_hash": "fixture",
        "environment_id": "fixture",
        "target": "fixture-item",
        "target_days": 30,
        "created_at": "2026-09-16T00:00:00Z",
        "updated_at": "2026-09-16T00:00:00Z",
    }
    rows = []
    for node in sorted(graph.nodes):
        for hops in (0, 1, 2):
            for kind in (None, "SellableItem", "Variant"):
                task = TaskRecord.model_validate(task_template | {"phase": node})
                view = {
                    "listing": {"kind": kind} if kind else None,
                    "observations": {},
                    "pending": None,
                    "pending_present": None,
                }
                context = {"task": task, "view": view, "plan": None, "last": {}, "alerts": {}}
                row = {"node": node, "hops": hops, "observed_type": kind}
                try:
                    local = SubgraphRetriever().retrieve(
                        graph, node, context, hops=hops, budget=config.pg_budget_bytes
                    )
                    bundle = SemanticContextBuilder().build(
                        registry=registry,
                        subgraph=local,
                        observed_type_ids=(kind,) if kind else (),
                        limits=SemanticDefinitionLimits(
                            max_definitions=config.semantic_max_definitions,
                            max_dependency_depth=config.semantic_max_dependency_depth,
                            semantic_budget_bytes=config.semantic_budget_bytes,
                        ),
                    )
                    row.update(
                        status="passed",
                        public_hash=bundle.content_hash,
                        bytes=bundle.diagnostics["included_bytes"],
                        required=bundle.diagnostics["required_definition_count"],
                        omitted_pg_edges=local["omitted_count"],
                        omitted_optional=bundle.diagnostics["omitted_optional_refs"],
                    )
                except (SemanticError, ValueError) as error:
                    row.update(
                        status="failed", error_code=getattr(error, "code", "PG_BUDGET_OR_STRUCTURE")
                    )
                rows.append(row)
    return {
        "passed": all(row["status"] == "passed" for row in rows),
        "cases": len(rows),
        "no_model_calls": True,
        "no_business_writes": True,
        "results": rows,
        "scope": "Real predicate-sorted local retrieval; unknown-fact fixtures, not model accuracy.",
    }


def run(args, root, config, registry, graph, release):
    from .execution import SOLVER_NOTICE

    guidance, solver = load_effective_prompts(
        root, release, guidance=GUIDANCE_SYSTEM, solver=SOLVER_NOTICE
    )
    if args.command in {
        "inspect-semantics",
        "preflight-semantics",
        "verify-semantics",
        "publish-semantic",
    }:
        registry.validate_semantic_refs(root / config.semantic_schema_path)
    if args.command == "inspect-semantics":
        report = inspect(root, config, registry, graph, root / args.fixture, args.node, args.hops)
    elif args.command == "preflight-semantics":
        report = preflight(config, registry, graph)
    elif args.command == "verify-semantics":
        identity = semantic_identity(root, graph, config, guidance=guidance, solver=solver)
        # Effective candidate paths are explicit; no fallback to the active deployment.
        candidate_config = root / args.out.parent / "effective-test-config.json"
        candidate_config.parent.mkdir(parents=True, exist_ok=True)
        candidate_config.write_text(json.dumps(config.model_dump()) + "\n")
        suites = {
            "semantic_tests": sorted(
                str(p.relative_to(root))
                for p in (root / "commerce-reasoning/tests").glob("test_semantic_*.py")
            ),
            "execution_safety": [
                "commerce-reasoning/tests/test_execution.py",
                "commerce-reasoning/tests/test_runtime.py",
                "commerce-reasoning/tests/test_host_release.py",
                "commerce-reasoning/tests/test_semantic_runtime.py",
            ],
        }
        report = {
            "run_id": uid("semantic-verification"),
            "identity": identity,
            "no_paid_model_calls": True,
        }
        for name, files in suites.items():
            if not files:
                raise SemanticError("SEMANTIC_SCHEMA_INVALID", "empty_test_suite")
            command = [sys.executable, "-m", "pytest", "-q", "--tb=short", *files]
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
                env=os.environ | {"COMMERCE_REASONING_TEST_CONFIG": str(candidate_config)},
            )
            text = result.stdout + result.stderr
            report[name] = {
                "passed": result.returncode == 0,
                "exit_code": result.returncode,
                "command": command,
                "output": text,
                "report_hash": content_hash(text),
                "identity": identity,
            }
        if identity != semantic_identity(root, graph, config, guidance=guidance, solver=solver):
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "source_changed_during_tests")
        report["passed"] = all(report[name]["passed"] for name in suites)
    elif args.command == "compare-semantics":
        baseline = json.loads((root / args.baseline).read_text())
        candidate = json.loads((root / args.candidate).read_text())
        tests = json.loads((root / args.verification).read_text())
        identity = semantic_identity(root, graph, config, guidance=guidance, solver=solver)
        accepted, reasons = compare_semantic_reports(baseline, candidate)
        for name in ("semantic_tests", "execution_safety"):
            if (
                tests.get(name, {}).get("identity") != identity
                or tests.get(name, {}).get("passed") is not True
            ):
                reasons.append(name + "_evidence_mismatch")
        if candidate.get("semantic_identity") != identity:
            reasons.append("candidate_identity_mismatch")
        report = {
            "kind": "semantic_extension",
            "run_id": uid("semantic-comparison"),
            "accepted": accepted and not reasons,
            "reasons": reasons,
            "identity": identity,
            "baseline": baseline,
            "candidate": candidate,
            "semantic_tests": tests.get("semantic_tests"),
            "execution_safety": tests.get("execution_safety"),
        }
    else:
        if args.knowledge_source != "working":
            raise ValueError("publish-semantic requires reviewed working candidate paths")
        report = publish_semantic(
            root,
            graph=graph,
            config=config,
            approved_by=args.approved_by,
            validation_path=root / args.validation,
            guidance=guidance,
            solver=solver,
        )
    report.update(knowledge_source=args.knowledge_source, builder_version=BUILDER_VERSION)
    write_json(root, args.out, report)
    print(
        json.dumps(
            {
                "output": str(root / args.out),
                "passed": report.get("passed"),
                "accepted": report.get("accepted"),
            },
            ensure_ascii=False,
        )
    )
    return 1 if report.get("passed") is False or report.get("accepted") is False else 0
