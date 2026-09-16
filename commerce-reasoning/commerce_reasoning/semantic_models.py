"""Versioned semantic definitions; these describe actions, never authorize them."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Description = Annotated[str, Field(min_length=1, max_length=600)]
Identifiers = Annotated[list[Identifier], Field(max_length=64)]
KINDS = ("actions", "states", "entities", "relations", "properties", "checks")
LEGACY_ACTION_FIELDS = ("id", "tool_binding", "effect", "side_effect", "allowed_origins", "checks")
BUILDER_VERSION = "1.0.0"


class SemanticError(ValueError):
    """Stable public error; do not expose configuration values or private paths."""

    def __init__(self, code: str, path: str = "") -> None:
        self.code, self.path = code, path
        super().__init__(code + (f": {path}" if path else ""))


class StrictDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SemanticRefGroup(StrictDefinition):
    entities: Identifiers
    relations: Identifiers
    properties: Identifiers

    @model_validator(mode="after")
    def unique_references(self) -> SemanticRefGroup:
        for kind in ("entities", "relations", "properties"):
            refs = getattr(self, kind)
            if len(refs) != len(set(refs)):
                raise ValueError(f"Duplicate {kind} reference")
        return self


class SemanticRefs(StrictDefinition):
    required: SemanticRefGroup
    optional: SemanticRefGroup

    @model_validator(mode="after")
    def disjoint_references(self) -> SemanticRefs:
        for kind in ("entities", "relations", "properties"):
            if set(getattr(self.required, kind)) & set(getattr(self.optional, kind)):
                raise ValueError(f"Required/optional {kind} references overlap")
        return self


class EntityDefinition(StrictDefinition):
    id: Identifier
    description: Description
    subtype_of: Identifier | None = None
    source: str | None = Field(default=None, max_length=300)
    key: str | None = Field(default=None, max_length=128)
    trusted_origin: Literal["host"] | None = None
    classification_rule: (
        Literal["nonempty_options", "not_family", "nonempty_variant_of_and_not_family"] | None
    ) = None


class RelationDefinition(StrictDefinition):
    id: Identifier
    description: Description
    domain: Annotated[list[Identifier], Field(min_length=1, max_length=32)]
    range: Annotated[list[Identifier], Field(min_length=1, max_length=32)]
    max_targets: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def unique_endpoints(self) -> RelationDefinition:
        for name in ("domain", "range"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError("Duplicate relation endpoint")
        return self


class PropertyDefinition(StrictDefinition):
    id: Identifier
    owner_ref: Identifier
    source_field: Annotated[
        str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    ]
    value_kind: Literal["integer", "number", "string", "boolean", "object", "array", "datetime"]
    description: Description
    unit: str | None = Field(default=None, max_length=40)


class ActionDefinition(StrictDefinition):
    id: Identifier
    tool_binding: Identifier
    effect: Identifier
    side_effect: bool
    allowed_origins: Annotated[list[Literal["agent", "host"]], Field(min_length=1, max_length=2)]
    checks: Identifiers
    description: Description
    semantic_refs: SemanticRefs

    @model_validator(mode="after")
    def unique_contract(self) -> ActionDefinition:
        for field in ("allowed_origins", "checks"):
            values = getattr(self, field)
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {field}")
        return self


class StateDefinition(StrictDefinition):
    id: Identifier
    label: Annotated[str, Field(min_length=1, max_length=160)]
    description: Description
    semantic_refs: SemanticRefs


class CheckDefinition(StrictDefinition):
    id: Identifier
    description: Description
    implementation: Annotated[str, Field(min_length=1, max_length=400)]
    immutable_to_refiner: Literal[True]


class SemanticOntology(StrictDefinition):
    schema_version: Literal["1.0"]
    semantic_schema_version: Literal["1.0"]
    ontology_id: Identifier
    version: Identifier
    status: str
    upstream_commit: str
    scope: dict[str, str]
    identity_key: list[str]
    value_statuses: list[str]
    change_statuses: list[str]
    entities: Annotated[list[EntityDefinition], Field(min_length=1, max_length=2048)]
    relations: Annotated[list[RelationDefinition], Field(max_length=2048)]
    actions: Annotated[list[ActionDefinition], Field(min_length=1, max_length=2048)]
    states: Annotated[list[StateDefinition], Field(min_length=1, max_length=2048)]
    properties: Annotated[list[PropertyDefinition], Field(max_length=2048)]
    check_catalog: Annotated[list[CheckDefinition], Field(max_length=2048)]
    invariants: list[str]
    restock_formula: dict[str, Any]


class SemanticDefinitionLimits(StrictDefinition):
    max_definitions: int = Field(default=64, ge=1, le=10000)
    max_dependency_depth: int = Field(default=12, ge=1, le=64)
    semantic_budget_bytes: int = Field(default=8000, ge=1, le=1000000)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def legacy_contract_projection(action: dict[str, Any]) -> dict[str, Any]:
    """Freeze the six original prompt fields; never strip actual execution checks."""
    if not all(field in action for field in LEGACY_ACTION_FIELDS):
        raise SemanticError("SEMANTIC_SCHEMA_INVALID", "legacy_action")
    return {field: copy.deepcopy(action[field]) for field in LEGACY_ACTION_FIELDS}


@dataclass(frozen=True)
class SemanticBundle:
    public: dict[str, Any]
    diagnostics: dict[str, Any]
    content_hash: str
