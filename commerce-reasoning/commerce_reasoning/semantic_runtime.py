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
