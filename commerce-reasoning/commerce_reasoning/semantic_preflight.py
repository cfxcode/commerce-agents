"""Full guide payload preflight using the same projection and serialization as runtime.

Fixtures are synthetic, typed stress inputs. The Cartesian cases do not claim all
business states are reachable, and no model call or business write is performed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .models import Coverage, EntityRef, Observation, RestockPlan, TaskRecord
from .procedural import SubgraphRetriever
from .semantic_audit import audit_definitions
from .semantic_models import SemanticError, content_hash
from .semantic_runtime import compose_semantics, guidance_budget, guidance_input, task_payload

PROFILES = ("fresh", "waiting", "conflict", "stale", "long_fields", "oversized")


def fixture(node: str, kind: str | None, profile: str, config) -> tuple[dict, list[dict]]:
    if profile not in PROFILES:
        raise ValueError("Unknown full payload profile")
    clock = datetime(2026, 9, 16, tzinfo=UTC)
    task = TaskRecord(
        task_id="fixture-task",
        turn_id="fixture-turn",
        merchant_id="fixture-merchant",
        operator="fixture-operator",
        session_hash="fixture-session",
        environment_id="fixture-env",
        target="fixture-item",
        target_days=30,
        phase=node,
        created_at=clock,
        updated_at=clock,
        host_outcome="applied" if node in {"VERIFY", "SUCCESS"} else None,
    )
    entity = EntityRef(
        merchant_id=task.merchant_id, object_type=kind or "Listing", external_id=task.target
    )
    values = {
        "stock": 12,
        "sales_last_30d": 90,
        "status": "active",
        "options": {},
        "variant_of": "fixture-family" if kind == "Variant" else None,
    }
    if profile == "long_fields":
        values["options"] = {"color": ["fixture-" + "蓝" * 90] * 8}
    elif profile == "oversized":
        values["options"] = {"color": ["x" * (config.guidance_input_budget_bytes + 1000)]}
    observations = {}
    for field, value in values.items():
        status = "unknown" if value is None else "stale" if profile == "stale" else "known"
        observation = Observation(
            observation_id="fixture-observation-" + field,
            task_id=task.task_id,
            merchant_id=task.merchant_id,
            entity_ref=entity,
            field=field,
            value=value,
            value_status=status,
            source_tool="get_listing",
            tool_use_id="fixture-call",
            observed_at=clock,
            source_updated_at=clock - timedelta(seconds=2),
            snapshot_id="fixture-snapshot",
            source_revision=1,
            coverage=Coverage(scope=task.target, complete=True),
        )
        observations[field] = observation.model_dump(mode="json")
    plan = None
    if profile in {"fresh", "waiting", "conflict", "long_fields", "oversized"}:
        plan = RestockPlan(
            plan_id="fixture-plan",
            task_id=task.task_id,
            task_revision=1,
            merchant_id=task.merchant_id,
            target=task.target,
            target_days=30,
            stock=12,
            sales=90,
            daily_rate="3",
            target_stock=90,
            quantity=78,
            evidence_ids=[
                observations[key]["observation_id"] for key in ("stock", "sales_last_30d")
            ],
            input_digest="a" * 64,
            target_revision=1,
            pending_snapshot="fixture-pending",
            created_at=clock,
            expires_at=clock + timedelta(seconds=300),
            note="计算依据保持未知与已知的区别。" * 80
            if profile == "long_fields"
            else "Fixture, not approval.",
        ).model_dump(mode="json")
    pending = profile in {"waiting", "conflict"}
    view = {
        "listing": {"kind": kind} if kind else None,
        "observations": observations,
        "pending": {"change_ids": ["fixture-change"] if pending else []},
        "pending_current": profile != "stale",
        "pending_present": None if profile == "stale" else pending,
    }
    events = [
        {
            "event_type": "tool_completed",
            "action_ref": "ReadListing",
            "status": "ok",
            "error_code": None,
        },
        {
            "event_type": "tool_completed",
            "action_ref": "ReadPendingChanges",
            "status": "ok",
            "error_code": None,
        },
        {
            "event_type": "action_blocked" if profile == "conflict" else "tool_completed",
            "action_ref": "StageRestock" if profile == "conflict" else "CalculateRestockPlan",
            "status": "blocked" if profile == "conflict" else "ok",
            "error_code": "PENDING_CHANGE_CONFLICT" if profile == "conflict" else None,
        },
    ]
    return {
        "task": task,
        "view": view,
        "plan": plan,
        "last": events[-1],
        "alerts": {"count": 1, "complete": True},
        "max_recovery_reads": config.max_recovery_reads,
    }, events


def full_payload_preflight(config, registry, graph, oracle: dict) -> dict:
    rows = []
    for node in sorted(graph.nodes):
        for hops in (0, 1, 2):
            for kind in (None, "SellableItem", "Variant"):
                for profile in PROFILES:
                    row = {
                        "node": node,
                        "hops": hops,
                        "observed_type": kind,
                        "profile": profile,
                        "expected": "reject_payload" if profile == "oversized" else "accept",
                    }
                    context, events = fixture(node, kind, profile, config)
                    try:
                        local = SubgraphRetriever().retrieve(
                            graph, node, context, hops=hops, budget=config.pg_budget_bytes
                        )
                        semantic = compose_semantics(registry, local, context["view"], config)
                        if semantic.bundle is None:
                            raise ValueError("Full semantic preflight requires closure")
                        actions = sorted(
                            {n["action_ref"] for n in local["nodes"] if n.get("action_ref")}
                        )
                        enabled = [
                            a for a in actions if "agent" in registry.actions[a]["allowed_origins"]
                        ]
                        data = guidance_input(
                            payload=task_payload(
                                context["task"],
                                context["view"],
                                context["plan"],
                                config.effective_variant,
                            ),
                            semantic=semantic,
                            subgraph=local,
                            view=context["view"],
                            enabled_actions=enabled,
                            events=events,
                            language="zh-CN",
                            config=config,
                        )
                        public = semantic.bundle.public
                        audit = audit_definitions(
                            semantic.bundle.diagnostics
                            | {
                                "included_definition_refs": [
                                    f"{category}:{item['id']}"
                                    for category in (
                                        "actions",
                                        "states",
                                        "entities",
                                        "relations",
                                        "properties",
                                        "checks",
                                    )
                                    for item in public[category]
                                ]
                            },
                            oracle,
                        )
                        budget = guidance_budget(data, config)
                        accepted = budget["within_budget"]
                        passed = (
                            accepted == (profile != "oversized") and audit.get("passed") is True
                        )
                        row.update(
                            **budget,
                            semantic_bytes=semantic.bundle.diagnostics["included_bytes"],
                            public_hash=semantic.bundle.content_hash,
                            payload_hash=content_hash(data),
                            audit=audit,
                            omitted_pg_edges=local["omitted_count"],
                            status="passed"
                            if passed and accepted
                            else "expected_rejection"
                            if passed
                            else "failed",
                        )
                    except (SemanticError, ValueError) as error:
                        row.update(
                            status="failed", error_code=getattr(error, "code", "STRUCTURE_ERROR")
                        )
                    rows.append(row)
    return {
        "schema_version": "1.0",
        "passed": all(r["status"] != "failed" for r in rows),
        "cases": len(rows),
        "accepted": sum(r["status"] == "passed" for r in rows),
        "expected_rejections": sum(r["status"] == "expected_rejection" for r in rows),
        "oracle_hash": content_hash(oracle),
        "results": rows,
        "no_model_calls": True,
        "no_business_writes": True,
        "scope": "Typed synthetic full guide inputs; exact runtime projection and wire JSON bytes. Not model accuracy or reachable-state coverage.",
    }
