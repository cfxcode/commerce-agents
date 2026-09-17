"""Strict loading and reference validation for definition-only semantic metadata."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .semantic_models import SemanticError, SemanticOntology, canonical_json, content_hash


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys before an overwritten value can disappear."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as error:
                raise SemanticError("SEMANTIC_SCHEMA_INVALID", "yaml_key") from error
            if duplicate:
                raise SemanticError("SEMANTIC_SCHEMA_INVALID", "duplicate_yaml_key")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def load_unique_yaml(path: Path) -> dict[str, Any]:
    """Only the explicit loader does I/O; the registry and builder use snapshots."""
    if path.stat().st_size > 1_000_000:
        raise SemanticError("SEMANTIC_SCHEMA_INVALID", "file_size")
    try:
        definition = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise SemanticError("SEMANTIC_SCHEMA_INVALID", "yaml") from error
    if not isinstance(definition, dict):
        raise SemanticError("SEMANTIC_SCHEMA_INVALID", "root")
    return definition


class SemanticRegistry:
    """Immutable, validated snapshot; returned values never alias stored definitions."""

    def __init__(self, definition: dict[str, Any]) -> None:
        if definition.get("semantic_schema_version") != "1.0":
            raise SemanticError("SEMANTIC_SCHEMA_INVALID", "semantic_schema_version")
        try:
            validated = SemanticOntology.model_validate(definition)
        except ValidationError as error:
            location = ".".join(str(part) for part in error.errors()[0]["loc"])
            raise SemanticError("SEMANTIC_SCHEMA_INVALID", location) from error
        # Canonical source identity is distinct from a single projected closure hash.
        self._definition = copy.deepcopy(definition)
        self.ontology_hash = content_hash(self._definition)
        self.version = validated.version
        self.schema = SemanticOntology.model_json_schema()
        self.schema_hash = content_hash(self.schema)
        self._catalogs: dict[str, dict[str, dict]] = {}
        for kind in ("actions", "states", "entities", "relations", "properties", "checks"):
            source = "check_catalog" if kind == "checks" else kind
            items = getattr(validated, source)
            catalog = {item.id: item.model_dump(exclude_none=True) for item in items}
            if len(catalog) != len(items):
                raise SemanticError("SEMANTIC_SCHEMA_INVALID", f"{kind}.duplicate_id")
            self._catalogs[kind] = catalog
        self._validate_references()

    def _require(self, kind: str, identifier: str, path: str) -> None:
        if identifier not in self._catalogs[kind]:
            elsewhere = any(identifier in rows for k, rows in self._catalogs.items() if k != kind)
            code = "SEMANTIC_REF_KIND_MISMATCH" if elsewhere else "SEMANTIC_REF_MISSING"
            raise SemanticError(code, path)

    def _validate_references(self) -> None:
        entities = self._catalogs["entities"]
        for identifier, item in entities.items():
            parent = item.get("subtype_of")
            if parent:
                self._require("entities", parent, f"entities.{identifier}.subtype_of")
        # Iterative path walks avoid recursion limits and distinguish inheritance from relations.
        resolved: set[str] = set()
        for root in sorted(entities):
            path: set[str] = set()
            current = root
            while current and current not in resolved:
                if current in path:
                    raise SemanticError("SEMANTIC_INHERITANCE_CYCLE", f"entities.{root}")
                path.add(current)
                current = entities[current].get("subtype_of")
            resolved.update(path)
        for identifier, item in self._catalogs["relations"].items():
            for field in ("domain", "range"):
                for target in item[field]:
                    self._require("entities", target, f"relations.{identifier}.{field}")
        for identifier, item in self._catalogs["properties"].items():
            self._require("entities", item["owner_ref"], f"properties.{identifier}.owner_ref")
        for kind in ("actions", "states"):
            for identifier, item in self._catalogs[kind].items():
                for level, groups in item["semantic_refs"].items():
                    for target_kind, targets in groups.items():
                        for target in targets:
                            self._require(
                                target_kind, target, f"{kind}.{identifier}.{level}.{target_kind}"
                            )
                for check in item.get("checks", []):
                    self._require("checks", check, f"{kind}.{identifier}.checks")

    def get(self, kind: str, identifier: str) -> dict:
        if kind not in self._catalogs:
            raise SemanticError("SEMANTIC_REF_KIND_MISMATCH", "kind")
        self._require(kind, identifier, f"{kind}.{identifier}")
        return copy.deepcopy(self._catalogs[kind][identifier])

    def get_action(self, identifier: str) -> dict:
        return self.get("actions", identifier)

    def get_state(self, identifier: str) -> dict:
        return self.get("states", identifier)

    def get_entity(self, identifier: str) -> dict:
        return self.get("entities", identifier)

    def get_relation(self, identifier: str) -> dict:
        return self.get("relations", identifier)

    def get_property(self, identifier: str) -> dict:
        return self.get("properties", identifier)

    def get_check(self, identifier: str) -> dict:
        item = self.get("checks", identifier)
        return {key: item[key] for key in ("id", "description")}

    def ancestors(self, identifier: str) -> tuple[str, ...]:
        current = self.get_entity(identifier)
        result = []
        while current.get("subtype_of"):
            result.append(current["subtype_of"])
            current = self.get_entity(current["subtype_of"])
        return tuple(result)

    def validate_schema_file(self, path: Path) -> None:
        """Bind the published schema to the validator actually used, with no remote refs."""
        import json

        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "semantic_schema") from error
        if canonical_json(schema) != canonical_json(self.schema):
            raise SemanticError("SEMANTIC_RELEASE_MISMATCH", "semantic_schema")
