"""Local knowledge validation, evaluation, replay, candidates and reviewed releases."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from .config import EvolutionConfig, ReasoningConfig
from .evaluation import evaluate
from .evolution import EvolutionRunner, activate, publish, validate_splits, validation_gate
from .models import digest, uid
from .procedural import load_knowledge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subs = parser.add_subparsers(dest="command", required=True)
    for name in (
        "validate-knowledge",
        "verify-safety",
        "evaluate",
        "evolve",
        "validate-candidate",
        "publish",
        "rollback",
        "replay",
    ):
        sub = subs.add_parser(name)
        sub.add_argument(
            "--config",
            type=Path,
            default=Path(
                "configs/evolution.yaml" if name == "evolve" else "configs/reasoning.yaml"
            ),
        )
        if name == "verify-safety":
            sub.add_argument("--out", type=Path, default=Path("runtime/safety.json"))
        if name == "validate-candidate":
            sub.add_argument("--baseline", type=Path, required=True)
            sub.add_argument("--candidate", type=Path, required=True)
            sub.add_argument("--safety-report", type=Path, required=True)
            sub.add_argument("--out", type=Path, default=Path("runtime/candidate-validation.json"))
        if name == "evaluate":
            sub.add_argument(
                "--manifest",
                type=Path,
                default=Path("evals/commerce_reasoning/manifests/pilot.json"),
            )
            sub.add_argument("--variant", choices=["C0", "O", "T", "P", "E"], required=True)
            sub.add_argument("--cases", help="Comma separated pilot case IDs")
            sub.add_argument("--out", type=Path, default=Path("runtime/evaluations"))
        if name == "evolve":
            sub.add_argument("--dry-run", action="store_true", default=True)
            sub.add_argument("--patch", type=Path)
            sub.add_argument("--training", type=Path)
            sub.add_argument("--out", type=Path, default=Path("runtime/candidates"))
        if name == "publish":
            sub.add_argument("--approved-by", required=True)
            sub.add_argument("--validation", type=Path, required=True)
            sub.add_argument("--initial", action="store_true")
        if name == "rollback":
            sub.add_argument("--manifest", type=Path, required=True)
        if name == "replay":
            sub.add_argument("--trace", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / "examples"))
    try:
        if args.command == "evolve":
            evolution = EvolutionConfig.from_file(root / args.config)
            validate_splits(
                root,
                [
                    root / path
                    for path in (
                        evolution.training_manifest,
                        evolution.validation_manifest,
                        evolution.test_manifest,
                    )
                ],
            )
            config = ReasoningConfig.from_file(root / evolution.reasoning_config)
        else:
            config = ReasoningConfig.from_file(root / args.config)
        ontology, graph = load_knowledge(root, config)
        if args.command == "verify-safety":
            checked = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "commerce-reasoning/tests/test_execution.py",
                    "commerce-reasoning/tests/test_runtime.py",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                env=os.environ | {"COMMERCE_REASONING_TEST_CONFIG": str(root / args.config)},
            )
            evidence = {
                "run_id": uid("safety"),
                "graph_hash": graph.content_hash,
                "safety_regression_passed": checked.returncode == 0,
                "exit_code": checked.returncode,
                "command": checked.args,
                "output": checked.stdout,
                "output_hash": digest(checked.stdout),
            }
            destination = root / args.out
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
            print(checked.stdout)
            print(f"Safety evidence: {destination}")
            return checked.returncode
        elif args.command == "validate-knowledge":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "ontology_hash": ontology.content_hash,
                        "graph_hash": graph.content_hash,
                        "nodes": len(graph.nodes),
                        "edges": len(graph.edges),
                    },
                    indent=2,
                )
            )
        elif args.command == "validate-candidate":
            baseline = json.loads((root / args.baseline).read_text())
            candidate = json.loads((root / args.candidate).read_text())
            safety = json.loads((root / args.safety_report).read_text())
            candidate["safety_regression_passed"] = bool(
                safety.get("safety_regression_passed")
                and safety.get("graph_hash") == candidate.get("graph_hash")
            )
            accepted, reasons = validation_gate(baseline, candidate)
            result = {
                "accepted": accepted,
                "reasons": reasons,
                "baseline": baseline,
                "candidate": candidate,
                "graph_hash": candidate.get("graph_hash"),
                "run_id": candidate.get("run_id"),
            }
            destination = root / args.out
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result, indent=2) + "\n")
            print(
                json.dumps({"accepted": accepted, "reasons": reasons, "output": str(destination)})
            )
            return 0 if accepted else 1
        elif args.command == "replay":
            events = [json.loads(line) for line in (root / args.trace).read_text().splitlines()]
            print(json.dumps({"events": events, "read_only": True}, ensure_ascii=False, indent=2))
        elif args.command == "rollback":
            activate(root, root / args.manifest)
            print("Active release switched; inventory was not changed.")
        elif args.command == "publish":
            print(
                json.dumps(
                    publish(
                        root,
                        graph=graph,
                        config=config,
                        approved_by=args.approved_by,
                        validation_path=root / args.validation,
                        initial=args.initial,
                    ),
                    indent=2,
                )
            )
        else:
            from anthropic import AsyncAnthropic
            from dotenv import load_dotenv

            client = None
            if args.command == "evaluate" or args.training:
                load_dotenv(root / ".env", override=False)
                client = AsyncAnthropic(timeout=60, max_retries=0)
            if args.command == "evaluate":
                report = asyncio.run(
                    evaluate(
                        root,
                        root / args.manifest,
                        args.variant,
                        client=client,
                        out=root / args.out,
                        cases_filter=set(args.cases.split(",")) if args.cases else None,
                        model=os.environ.get("COMMERCE_MODEL"),
                        reasoning_config=config,
                    )
                )
                print(
                    json.dumps(
                        {
                            "run_id": report["run_id"],
                            "submitted": report["submitted"],
                            "successes": report["successes"],
                            "output": str(root / args.out / report["run_id"]),
                        }
                    )
                )
                return 0 if report["successes"] == report["submitted"] else 1
            runner = EvolutionRunner(root / args.out, graph)
            if args.patch:
                result = runner.consider(json.loads((root / args.patch).read_text()))
            elif args.training:
                result = asyncio.run(
                    runner.propose(
                        client,
                        os.environ.get("COMMERCE_MODEL", "claude-opus-5"),
                        json.loads((root / args.training).read_text()),
                        (root / "knowledge/prompts/refiner.txt").read_text(),
                    )
                )
            else:
                raise ValueError("evolve requires --patch or training diagnostics via --training")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["status"] == "rejected" else 0
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
