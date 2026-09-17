"""Pure, bounded semantic dependency expansion for the retained local PG nodes."""

from __future__ import annotations

from collections import deque
from typing import Any

from .semantic_models import (
    BUILDER_VERSION,
    KINDS,
    SemanticBundle,
    SemanticDefinitionLimits,
    SemanticError,
    canonical_json,
    content_hash,
)
from .semantic_registry import SemanticRegistry

Ref = tuple[str, str]
PROJECTION = {
    "actions": (
        "id",
        "description",
        "tool_binding",
        "effect",
        "side_effect",
        "allowed_origins",
        "checks",
    ),
    "states": ("id", "label", "description"),
    "entities": ("id", "description", "subtype_of", "classification_rule"),
    "relations": ("id", "description", "domain", "range", "max_targets"),
    "properties": ("id", "description", "owner_ref", "source_field", "value_kind", "unit"),
    "checks": ("id", "description"),
}


def _name(ref: Ref) -> str:
    return f"{ref[0]}:{ref[1]}"


def _dependencies(registry: SemanticRegistry, ref: Ref) -> list[Ref]:
    kind, identifier = ref
    item = registry.get(kind, identifier)
    result: set[Ref] = set()
    if kind in {"actions", "states"}:
        for target_kind, ids in item["semantic_refs"]["required"].items():
            result.update((target_kind, target) for target in ids)
        result.update(("checks", check) for check in item.get("checks", []))
    elif kind == "entities" and item.get("subtype_of"):
        result.add(("entities", item["subtype_of"]))
    elif kind == "relations":
        result.update(("entities", target) for target in item["domain"] + item["range"])
    elif kind == "properties":
        result.add(("entities", item["owner_ref"]))
    return sorted(result)


def _project(registry: SemanticRegistry, refs: set[Ref]) -> dict[str, Any]:
    public: dict[str, Any] = {"schema_version": "1.0", "ontology_version": registry.version}
    for kind in KINDS:
        public[kind] = []
        for _, identifier in sorted(ref for ref in refs if ref[0] == kind):
            item = registry.get(kind, identifier)
            record = {key: item[key] for key in PROJECTION[kind] if key in item}
            # These arrays are sets semantically; source order must not change public hashes.
            for field in ("domain", "range", "checks", "allowed_origins"):
                if field in record:
                    record[field] = sorted(record[field])
            public[kind].append(record)
    return public


def _close(
    registry: SemanticRegistry,
    root: Ref,
    limits: SemanticDefinitionLimits,
    initial_depth: int = 0,
) -> tuple[set[Ref], dict[Ref, tuple[str, ...]]]:
    refs: set[Ref] = set()
    paths: dict[Ref, tuple[str, ...]] = {}
    deepest: dict[Ref, int] = {}
    queue = deque([(root, initial_depth, (_name(root),))])
    while queue:
        ref, depth, path = queue.popleft()
        if depth > limits.max_dependency_depth:
            raise SemanticError("SEMANTIC_DEPTH_EXCEEDED", _name(ref))
        if ref not in paths or (len(path), path) < (len(paths[ref]), paths[ref]):
            paths[ref] = path
        if depth <= deepest.get(ref, -1):
            continue
        deepest[ref] = depth
        registry.get(*ref)
        refs.add(ref)
        if len(refs) > limits.max_definitions:
            raise SemanticError("SEMANTIC_BUDGET_EXCEEDED", "definition_count")
        for target in _dependencies(registry, ref):
            queue.append((target, depth + 1, path + (_name(target),)))
    return refs, paths


class SemanticContextBuilder:
    """Definitions only: no model calls, network, storage writes, facts or permissions."""

    def build(
        self,
        *,
        registry: Any,
        subgraph: dict,
        observed_type_ids: tuple[str, ...] = (),
        limits: SemanticDefinitionLimits | None = None,
    ) -> SemanticBundle:
        limits = limits or SemanticDefinitionLimits()
        if not isinstance(registry, SemanticRegistry):
            cached = getattr(registry, "semantic_registry", None)
            registry = cached or SemanticRegistry(registry.definition)
        seeds: dict[Ref, set[str]] = {}
        nodes = subgraph.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise SemanticError("SEMANTIC_SCHEMA_INVALID", "subgraph.nodes")
        seen = set()
        for node in nodes:
            if not isinstance(node, dict):
                raise SemanticError("SEMANTIC_SCHEMA_INVALID", "subgraph.node")
            identifier = node.get("id")
            if not isinstance(identifier, str) or identifier in seen:
                raise SemanticError("SEMANTIC_SCHEMA_INVALID", "subgraph.node_id")
            seen.add(identifier)
            kind = node.get("kind")
            if kind == "action":
                field, target_kind, forbidden = "action_ref", "actions", "state_ref"
            elif kind in {"decision", "state", "terminal"}:
                field, target_kind, forbidden = "state_ref", "states", "action_ref"
            else:
                raise SemanticError("SEMANTIC_SCHEMA_INVALID", "subgraph.kind")
            target = node.get(field)
            if not isinstance(target, str) or forbidden in node:
                raise SemanticError("SEMANTIC_SCHEMA_INVALID", f"subgraph.{field}")
            seeds.setdefault((target_kind, target), set()).add(f"PG:{identifier}")
        if subgraph.get("current_node") not in seen:
            raise SemanticError("SEMANTIC_SCHEMA_INVALID", "subgraph.current_node")
        if any(not isinstance(identifier, str) for identifier in observed_type_ids):
            raise SemanticError("SEMANTIC_SCHEMA_INVALID", "observed_type_ids")
        for identifier in sorted(set(observed_type_ids)):
            seeds.setdefault(("entities", identifier), set()).add(f"observed_type:{identifier}")

        required: set[Ref] = set()
        traces: dict[Ref, dict[str, Any]] = {}

        def record(
            paths: dict[Ref, tuple[str, ...]], sources: set[str], prefix: tuple[str, ...] = ()
        ) -> None:
            for ref, path in sorted(paths.items()):
                candidate = prefix + path
                row = traces.setdefault(ref, {"path": candidate, "seed_sources": set()})
                if (len(candidate), candidate) < (len(row["path"]), row["path"]):
                    row["path"] = candidate
                row["seed_sources"].update(sources)

        # All required roots are closed before any optional candidate is considered.
        for seed, sources in sorted(seeds.items()):
            group, paths = _close(registry, seed, limits)
            required.update(group)
            record(paths, sources)
        self._check_size(registry, required, limits)
        selected = set(required)
        optional: dict[Ref, set[str]] = {}
        optional_parents: dict[Ref, set[str]] = {}
        for seed, sources in sorted(seeds.items()):
            if seed[0] not in {"actions", "states"}:
                continue
            for kind, identifiers in registry.get(*seed)["semantic_refs"]["optional"].items():
                for identifier in identifiers:
                    optional.setdefault((kind, identifier), set()).update(sources)
                    optional_parents.setdefault((kind, identifier), set()).add(_name(seed))
        omitted = []
        for seed, sources in sorted(optional.items()):
            try:
                group, paths = _close(registry, seed, limits, initial_depth=1)
                candidate = selected | group
                self._check_size(registry, candidate, limits)
            except SemanticError as error:
                if error.code not in {"SEMANTIC_DEPTH_EXCEEDED", "SEMANTIC_BUDGET_EXCEEDED"}:
                    raise
                omitted.append({"kind": seed[0], "id": seed[1], "reason": error.code})
                continue
            selected = candidate
            record(paths, sources, (min(optional_parents[seed]), "optional"))
        public = _project(registry, selected)
        diagnostics = {
            "builder_version": BUILDER_VERSION,
            "ontology_hash": registry.ontology_hash,
            "semantic_schema_hash": registry.schema_hash,
            "seed_action_refs": sorted(ref[1] for ref in seeds if ref[0] == "actions"),
            "seed_state_refs": sorted(ref[1] for ref in seeds if ref[0] == "states"),
            "observed_type_ids": sorted(set(observed_type_ids)),
            "required_definition_count": len(required),
            "optional_definition_count": len(selected - required),
            "included_bytes": len(canonical_json(public).encode("utf-8")),
            "omitted_optional_refs": omitted,
            "dependency_paths": [
                {
                    "kind": ref[0],
                    "id": ref[1],
                    "required": ref in required,
                    "path": list(traces[ref]["path"]),
                    "seed_sources": sorted(traces[ref]["seed_sources"]),
                }
                for ref in sorted(selected)
            ],
            "status": "partial_optional" if omitted else "complete",
        }
        return SemanticBundle(public, diagnostics, content_hash(public))

    @staticmethod
    def _check_size(
        registry: SemanticRegistry, refs: set[Ref], limits: SemanticDefinitionLimits
    ) -> None:
        if len(refs) > limits.max_definitions:
            raise SemanticError("SEMANTIC_BUDGET_EXCEEDED", "definition_count")
        if (
            len(canonical_json(_project(registry, refs)).encode("utf-8"))
            > limits.semantic_budget_bytes
        ):
            raise SemanticError("SEMANTIC_BUDGET_EXCEEDED", "semantic_budget_bytes")
