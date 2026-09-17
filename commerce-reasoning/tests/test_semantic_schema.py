"""Offline schema checks; legacy records are pinned to the reviewed base commit."""

import copy
import json
from pathlib import Path

import pytest

from commerce_reasoning.semantic_models import (
    SemanticError,
    SemanticOntology,
    legacy_contract_projection,
)
from commerce_reasoning.semantic_registry import SemanticRegistry, load_unique_yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures/semantic_context"


@pytest.fixture
def definition():
    return load_unique_yaml(ROOT / "knowledge/ontology/retail.v1.yaml")


def test_all_definitions_and_checked_in_schema(definition):
    registry = SemanticRegistry(definition)
    assert len(definition["actions"]) == len(definition["states"]) == 9
    assert len(definition["entities"]) == 11 and len(definition["properties"]) == 14
    assert len(definition["check_catalog"]) == 16
    for kind in ("actions", "states"):
        for item in definition[kind]:
            assert item["description"] and set(item["semantic_refs"]) == {"required", "optional"}
    for item in definition["properties"]:
        assert registry.get_entity(item["owner_ref"])
    registry.validate_schema_file(ROOT / "knowledge/ontology/ontology.semantic.schema.json")
    assert SemanticOntology.model_json_schema() == json.loads(
        (ROOT / "knowledge/ontology/ontology.semantic.schema.json").read_text()
    )


def test_legacy_projection_is_frozen_and_returns_no_alias(definition):
    expected = json.loads((FIXTURES / "expected/legacy-contracts.json").read_text())
    old = load_unique_yaml(FIXTURES / "legacy-ontology.yaml")
    assert {a["id"]: a for a in old["actions"]} == expected
    assert {a["id"]: legacy_contract_projection(a) for a in definition["actions"]} == expected
    projected = legacy_contract_projection(definition["actions"][0])
    projected["checks"].clear()
    assert definition["actions"][0]["checks"]
    with pytest.raises(SemanticError, match="semantic_schema_version"):
        SemanticRegistry(old)


@pytest.mark.parametrize(
    "kind", ["actions", "states", "entities", "relations", "properties", "check_catalog"]
)
def test_duplicate_ids_rejected(definition, kind):
    definition[kind].append(copy.deepcopy(definition[kind][0]))
    with pytest.raises(SemanticError, match="SEMANTIC_SCHEMA_INVALID"):
        SemanticRegistry(definition)


@pytest.mark.parametrize(
    "kind", ["actions", "states", "entities", "relations", "properties", "check_catalog"]
)
def test_unknown_fields_rejected(definition, kind):
    definition[kind][0]["unexpected"] = "not silently dropped"
    with pytest.raises(SemanticError, match="SEMANTIC_SCHEMA_INVALID"):
        SemanticRegistry(definition)


@pytest.mark.parametrize("kind", ["actions", "states"])
def test_missing_and_invalid_dependencies(definition, kind):
    item = definition[kind][0]
    saved = copy.deepcopy(item)
    del item["semantic_refs"]
    with pytest.raises(SemanticError, match="SEMANTIC_SCHEMA_INVALID"):
        SemanticRegistry(definition)
    item.update(saved)
    item["semantic_refs"]["required"]["entities"] = ["Missing"]
    with pytest.raises(SemanticError, match="SEMANTIC_REF_MISSING"):
        SemanticRegistry(definition)
    item["semantic_refs"]["required"]["entities"] = ["plan_for"]
    with pytest.raises(SemanticError, match="SEMANTIC_REF_KIND_MISMATCH"):
        SemanticRegistry(definition)


def test_duplicate_reference_and_required_optional_overlap(definition):
    group = definition["actions"][0]["semantic_refs"]
    group["required"]["entities"] = ["Listing", "Listing"]
    with pytest.raises(SemanticError, match="SEMANTIC_SCHEMA_INVALID"):
        SemanticRegistry(definition)
    group["required"]["entities"] = ["Listing"]
    group["optional"]["entities"] = ["Listing"]
    with pytest.raises(SemanticError, match="SEMANTIC_SCHEMA_INVALID"):
        SemanticRegistry(definition)


@pytest.mark.parametrize("change", ["parent", "endpoint", "owner", "check"])
def test_dangling_reference_rejected(definition, change):
    if change == "parent":
        definition["entities"][0]["subtype_of"] = "Missing"
    elif change == "endpoint":
        definition["relations"][0]["range"] = ["Missing"]
    elif change == "owner":
        definition["properties"][0]["owner_ref"] = "Missing"
    else:
        definition["actions"][0]["checks"] = ["Missing"]
    with pytest.raises(SemanticError, match="SEMANTIC_REF_MISSING"):
        SemanticRegistry(definition)


def test_inheritance_cycle_rejected_but_business_relation_cycle_allowed(definition):
    listing = next(e for e in definition["entities"] if e["id"] == "Listing")
    listing["subtype_of"] = "Variant"
    with pytest.raises(SemanticError, match="SEMANTIC_INHERITANCE_CYCLE"):
        SemanticRegistry(definition)
    del listing["subtype_of"]
    definition["relations"].append(
        {
            "id": "loop",
            "description": "A business relation, not inheritance.",
            "domain": ["Listing"],
            "range": ["Listing"],
        }
    )
    assert SemanticRegistry(definition).get_relation("loop")


@pytest.mark.parametrize(
    "text", ["version: one\nversion: two\n", "item:\n  id: A\n  id: B\n", "<<: {id: A}\nid: B\n"]
)
def test_duplicate_yaml_mapping_keys_are_not_overwritten(tmp_path, text):
    path = tmp_path / "duplicate.yaml"
    path.write_text(text)
    with pytest.raises(SemanticError, match="duplicate_yaml_key"):
        load_unique_yaml(path)


def test_descriptions_identifiers_and_source_fields_are_bounded(definition):
    for key, value in [("description", "x" * 601), ("id", "not an id")]:
        candidate = copy.deepcopy(definition)
        candidate["entities"][0][key] = value
        with pytest.raises(SemanticError, match="SEMANTIC_SCHEMA_INVALID"):
            SemanticRegistry(candidate)
    definition["properties"][0]["source_field"] = "__import__('os')"
    with pytest.raises(SemanticError, match="SEMANTIC_SCHEMA_INVALID"):
        SemanticRegistry(definition)


def test_getters_do_not_modify_registry_and_hide_check_implementation(definition):
    registry = SemanticRegistry(definition)
    original = registry.ontology_hash
    action = registry.get_action("StageRestock")
    action["semantic_refs"]["required"]["entities"].clear()
    assert registry.get_action("StageRestock")["semantic_refs"]["required"]["entities"]
    assert registry.ontology_hash == original
    assert set(registry.get_check("HOST_APPROVAL")) == {"id", "description"}
    assert registry.ancestors("Variant") == ("SellableItem", "Listing")


def test_pg_only_changes_compatibility_versions():
    old = json.loads((FIXTURES / "legacy-pg.json").read_text())
    new = json.loads((ROOT / "knowledge/pg/inventory_restock.v1.json").read_text())
    assert new["version"] == "1.0.1" and new["ontology_version"] == "1.1.0"
    new.update(version=old["version"], ontology_version=old["ontology_version"])
    assert old == new
