"""Definition-context assembly without changing tools, facts or authorization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .semantic_context import SemanticContextBuilder
from .semantic_models import (
    SemanticBundle,
    SemanticDefinitionLimits,
    canonical_json,
    legacy_contract_projection,
)


@dataclass(frozen=True)
class SemanticInput:
    fields: dict[str, Any]
    bundle: SemanticBundle | None


def compose_semantics(registry: Any, subgraph: dict, view: dict, config: Any) -> SemanticInput:
    """Only the retained nodes and confirmed type seed the closure; facts stay separate."""
    mode = config.effective_semantic_mode
    actions = sorted({node["action_ref"] for node in subgraph["nodes"] if node.get("action_ref")})
    if mode == "legacy":
        return SemanticInput(
            {
                "action_contracts": {
                    a: legacy_contract_projection(registry.contract(a)) for a in actions
                }
            },
            None,
        )
    listing = view.get("listing")
    target_type = listing.get("kind") if listing else None
    # This value is supplied by ObservationAdapter, not by the model or graph text.
    observed = (target_type,) if target_type and target_type != "unknown" else ()
    bundle = SemanticContextBuilder().build(
        registry=registry,
        subgraph=subgraph,
        observed_type_ids=observed,
        limits=SemanticDefinitionLimits(
            max_definitions=config.semantic_max_definitions,
            max_dependency_depth=config.semantic_max_dependency_depth,
            semantic_budget_bytes=config.semantic_budget_bytes,
        ),
    )
    return SemanticInput({"semantic_definitions": bundle.public}, bundle)


def input_bytes(data: dict, *, canonical: bool) -> int:
    """Byte accounting is not token estimation; preserve legacy serialization separately."""
    if canonical:
        return len(canonical_json(data).encode("utf-8"))
    import json

    return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def task_payload(task: Any, view: dict, plan: dict | None, variant: str) -> dict:
    """The runtime and offline preflight share this exact facts projection."""
    payload: dict[str, Any] = {
        "task": {
            "target": task.target,
            "target_days": task.target_days,
            "unknowns": list(task.unknowns),
            "phase": task.phase,
        }
    }
    if variant != "C0":
        payload["semantic_context"] = {
            "target_kind": view["listing"]["kind"] if view.get("listing") else "unknown",
            "facts": {
                key: {field: value[field] for field in ("value", "value_status", "observation_id")}
                for key, value in view["observations"].items()
            },
            "pending_present": view["pending_present"],
            "plan": plan,
        }
    return payload


def guidance_input(
    *,
    payload: dict,
    semantic: SemanticInput,
    subgraph: dict,
    view: dict,
    enabled_actions: list[str],
    events: list[dict],
    language: str,
    config: Any,
) -> dict:
    """Build the actual guide input, without invoking any model or modifying facts."""
    data = {
        **payload,
        "response_language": language,
        "enabled_actions": enabled_actions,
        **semantic.fields,
        "evidence_ids": [o["observation_id"] for o in view["observations"].values()],
        "edge_ids": [edge["id"] for edge in subgraph["edges"]],
        "recent_events": [
            {key: event.get(key) for key in ("event_type", "action_ref", "status", "error_code")}
            for event in events[-config.recent_events :]
        ],
    }
    if config.effective_variant == "T":
        data["steps"] = [
            {
                "id": edge["id"],
                **{
                    key: edge[key]
                    for key in ("condition", "guidance", "pitfalls", "predicate_status")
                },
            }
            for edge in subgraph["edges"]
        ]
    else:
        data["subgraph"] = subgraph
    return data


def guidance_budget(data: dict, config: Any) -> dict:
    """Measure the exact json.dumps serialization used by model_json, not tokens."""
    size = input_bytes(data, canonical=False)
    limit = (
        config.guidance_input_budget_bytes
        if config.effective_semantic_mode == "closure"
        else config.context_budget_tokens * 3
    )
    return {
        "guidance_input_bytes": size,
        "guidance_input_limit_bytes": limit,
        "within_budget": size <= limit,
    }
