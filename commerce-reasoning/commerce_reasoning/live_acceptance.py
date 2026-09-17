"""Bounded, explicit live validation. Missing credentials never become fake test results.

This command only changes isolated evaluation fixtures and runtime reports. It
cannot merge a PR, publish knowledge, switch active, or modify production data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class ModelBudgetExceeded(RuntimeError):
    pass


@dataclass
class ModelBudget:
    max_calls: int = 500
    max_tokens: int = 2_000_000
    calls: int = 0
    tokens: int = 0
    unmetered_calls: int = 0

    def reserve(self, request: dict) -> None:
        if self.calls >= self.max_calls or self.tokens >= self.max_tokens or self.unmetered_calls:
            raise ModelBudgetExceeded("Live model budget exhausted or usage is unknown")
        if len(json.dumps(request, ensure_ascii=False, default=str).encode()) > 250_000:
            raise ModelBudgetExceeded("Live request exceeds the 250 KB input-envelope cap")
        if not 1 <= request.get("max_tokens", 0) <= 2000:
            raise ModelBudgetExceeded("Live output reservation exceeds the per-call cap")
        self.calls += 1

    def record(self, response) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            self.unmetered_calls += 1
            return
        self.tokens += sum(
            getattr(usage, name, 0) or 0
            for name in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            )
        )


class BudgetedStream:
    def __init__(self, stream, budget):
        self.stream, self.budget, self.measured = stream, budget, False

    async def __aenter__(self):
        try:
            self.opened = await self.stream.__aenter__()
        except BaseException:
            self.budget.unmetered_calls += 1
            self.measured = True
            raise
        return self

    def __aiter__(self):
        return self.opened.__aiter__()

    async def get_final_message(self):
        response = await self.opened.get_final_message()
        if not self.measured:
            self.budget.record(response)
            self.measured = True
        return response

    async def __aexit__(self, *exc):
        if not self.measured:
            self.budget.unmetered_calls += 1
            self.measured = True
        return await self.stream.__aexit__(*exc)


class BudgetedMessages:
    def __init__(self, messages, budget):
        self.messages, self.budget = messages, budget

    async def create(self, **request):
        self.budget.reserve(request)
        try:
            response = await self.messages.create(**request)
        except BaseException:
            self.budget.unmetered_calls += 1
            raise
        self.budget.record(response)
        return response

    def stream(self, **request):
        self.budget.reserve(request)
        try:
            stream = self.messages.stream(**request)
        except BaseException:
            self.budget.unmetered_calls += 1
            raise
        return BudgetedStream(stream, self.budget)


def prerequisites(environment: dict[str, str]) -> dict:
    missing = [key for key in ("ANTHROPIC_API_KEY", "COMMERCE_MODEL") if not environment.get(key)]
    model = environment.get("COMMERCE_MODEL", "")
    endpoint = environment.get("ANTHROPIC_BASE_URL", "")
    if model and not model.startswith("claude-") and not endpoint:
        missing.append("ANTHROPIC_BASE_URL")
    invalid = []
    if endpoint:
        parsed = urlparse(endpoint)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
            or parsed.scheme != "https"
            and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})
        ):
            invalid.append("ANTHROPIC_BASE_URL")
    return {
        "ready": not missing and not invalid,
        "missing": missing,
        "invalid": invalid,
        "status": "ready" if not missing and not invalid else "blocked",
        "real_model_calls": 0,
    }


async def run(root: Path, out: Path, *, validation: bool, max_calls: int, max_tokens: int) -> dict:
    from anthropic import AsyncAnthropic

    from .config import ReasoningConfig
    from .evaluation import evaluate
    from .semantic_evaluation import compare_semantic_reports

    checked = prerequisites(dict(os.environ))
    if not checked["ready"]:
        return checked
    budget = ModelBudget(max_calls=max_calls, max_tokens=max_tokens)
    report = {
        "status": "running",
        "stages": {},
        "publication_performed": False,
        "limits": {
            "max_calls": max_calls,
            "max_returned_tokens": max_tokens,
            "request_bytes": 250000,
            "wall_seconds": 1800,
            "token_overshoot": "At most one in-flight bounded request; token usage is only known after response.",
        },
    }
    configs = {
        mode: ReasoningConfig.from_file(root / f"configs/experiments/p-{mode}.yaml")
        for mode in ("legacy", "closure")
    }
    async with AsyncAnthropic(timeout=60, max_retries=0) as provider:

        class Client:
            messages = BudgetedMessages(provider.messages, budget)

        try:
            async with asyncio.timeout(1800):
                stages = ["smoke", "validation"] if validation else ["smoke"]
                for stage in stages:
                    results = {}
                    for mode in ("legacy", "closure"):
                        current = await evaluate(
                            root,
                            root
                            / f"evals/commerce_reasoning/manifests/{'pilot' if stage == 'smoke' else 'validation'}.json",
                            "P",
                            client=Client(),
                            out=out / stage / mode,
                            cases_filter={"T01", "T03", "T11"} if stage == "smoke" else None,
                            model=os.environ["COMMERCE_MODEL"],
                            reasoning_config=configs[mode],
                        )
                        # Only the complete aggregate report is publishable; raw traces remain local.
                        results[mode] = current
                        if current["valid"] != current["submitted"] or budget.unmetered_calls:
                            report["stages"][stage] = results
                            report["status"] = "blocked_provider_or_budget"
                            return report | {
                                "real_model_calls": budget.calls,
                                "returned_tokens": budget.tokens,
                                "unmetered_calls": budget.unmetered_calls,
                            }
                    accepted, reasons = compare_semantic_reports(
                        results["legacy"], results["closure"]
                    )
                    report["stages"][stage] = {
                        "reports": results,
                        "comparison_accepted": accepted,
                        "reasons": reasons,
                    }
                    if (
                        not accepted
                        or any(r["successes"] != r["submitted"] for r in results.values())
                        and stage == "smoke"
                    ):
                        report["status"] = f"{stage}_rejected"
                        break
                else:
                    report["status"] = "validation_complete" if validation else "smoke_complete"
        except TimeoutError:
            report["status"] = "blocked_wall_budget"
        except Exception as error:
            report["status"] = "failed"
            report["error_type"] = type(error).__name__
    report.update(
        real_model_calls=budget.calls,
        returned_tokens=budget.tokens,
        unmetered_calls=budget.unmetered_calls,
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, default=Path("runtime/live-semantic-acceptance"))
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--validation", action="store_true")
    parser.add_argument("--max-calls", type=int, default=500)
    parser.add_argument("--max-tokens", type=int, default=2_000_000)
    args = parser.parse_args()
    if not 1 <= args.max_calls <= 500 or not 1 <= args.max_tokens <= 2_000_000:
        parser.error("Budgets must be positive and within the fixed reviewed maximums")
    root = args.root.resolve()
    sys.path.insert(0, str(root / "examples"))
    out = (root / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    checked = prerequisites(dict(os.environ))
    result = (
        checked
        if args.check_only or not checked["ready"]
        else asyncio.run(
            run(
                root,
                out,
                validation=args.validation,
                max_calls=args.max_calls,
                max_tokens=args.max_tokens,
            )
        )
    )
    (out / "status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("status", "missing", "invalid", "real_model_calls")
                if key in result
            }
        )
    )
    if result["status"] == "blocked":
        return 78
    return 0 if result["status"] in {"ready", "smoke_complete", "validation_complete"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
