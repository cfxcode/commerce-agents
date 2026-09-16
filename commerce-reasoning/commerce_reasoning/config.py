"""Independent deployment configuration. No credentials belong in this file."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ReasoningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    variant: Literal["C0", "O", "T", "P", "E"] = "P"
    ontology_path: str = "knowledge/ontology/retail.v1.yaml"
    predicates_path: str = "knowledge/ontology/predicates.v1.yaml"
    pg_path: str = "knowledge/pg/inventory_restock.v1.json"
    schema_path: str = "knowledge/pg/pg.schema.json"
    release_manifest: str = "knowledge/releases/active.json"
    audit_store: str = "runtime/reasoning.sqlite"
    execution_mode: Literal["serial"] = "serial"
    guidance_model: str | None = None
    guidance_timeout_s: float = Field(default=8, gt=0)
    guidance_max_tokens: int = Field(default=500, ge=100)
    context_budget_tokens: int = Field(default=2000, ge=100)
    hops: int = Field(default=2, ge=0, le=2)
    recent_events: int = Field(default=3, ge=1, le=10)
    max_recovery_reads: int = Field(default=1, ge=0, le=3)
    observation_ttl_s: int = Field(default=60, gt=0)
    plan_ttl_s: int = Field(default=300, gt=0)
    evolution_enabled: bool = False
    debug_enabled: bool = True

    @classmethod
    def from_file(cls, path: Path) -> "ReasoningConfig":
        return cls.model_validate(yaml.safe_load(path.read_text()) or {})


class EvolutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reasoning_config: str = "configs/reasoning.yaml"
    max_candidates: int = Field(default=1, ge=1, le=10)
    repetitions: int = Field(default=3, ge=3)
    max_token_ratio: float = Field(default=1.5, ge=1)
    training_manifest: str = "evals/commerce_reasoning/manifests/training.json"
    validation_manifest: str = "evals/commerce_reasoning/manifests/validation.json"
    test_manifest: str = "evals/commerce_reasoning/manifests/test.json"

    @classmethod
    def from_file(cls, path: Path) -> "EvolutionConfig":
        return cls.model_validate(yaml.safe_load(path.read_text()) or {})
