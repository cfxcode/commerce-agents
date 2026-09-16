"""Executable operational ontology and observations, without provider dependencies."""

from datetime import datetime, timedelta
from fractions import Fraction
from math import ceil
from pathlib import Path
from typing import Any

import yaml

from .models import (
    Blocked,
    Coverage,
    EntityRef,
    Observation,
    PendingChangesSnapshot,
    RestockPlan,
    TaskRecord,
    digest,
    uid,
)
from .storage import Store

CHECKS = frozenset(
    {
        "ACTION_RECEIPT",
        "APPROVAL_DIGEST",
        "ATOMIC_COMMIT",
        "COMPLETE_PENDING_SNAPSHOT",
        "COVERAGE_CAPTURE",
        "CURRENT_REVISION",
        "FRESH_INPUTS",
        "HOST_APPROVAL",
        "IDEMPOTENCY",
        "PENDING_CONFLICT_ATOMIC",
        "PLAN_MATCH",
        "STAGED_STATUS",
        "TENANT_SCOPE",
        "UPSTREAM_GUARDRAILS",
        "UPSTREAM_PROVENANCE",
        "VALID_TARGET",
    }
)


class OntologyRegistry:
    def __init__(self, path: Path):
        self.definition = yaml.safe_load(path.read_text())
        self.entities = self._index("entities")
        self.actions = self._index("actions")
        self.states = self._index("states")
        self.relations = self._index("relations")
        checks = self._index("check_catalog")
        if set(checks) != CHECKS:
            raise ValueError("Ontology check registry differs from implemented checks")
        for entity in self.entities.values():
            if entity.get("subtype_of") and entity["subtype_of"] not in self.entities:
                raise ValueError("Unknown parent entity")
        for relation in self.relations.values():
            if not set(relation["domain"] + relation["range"]) <= self.entities.keys():
                raise ValueError("Unknown relation endpoint")
        for action in self.actions.values():
            if not set(action["checks"]) <= CHECKS:
                raise ValueError("Unknown action check")
        self.content_hash = digest(self.definition)

    def _index(self, field: str) -> dict:
        items = self.definition[field]
        result = {item["id"]: item for item in items}
        if len(result) != len(items):
            raise ValueError(f"Duplicate {field} IDs")
        return result

    @staticmethod
    def classify(listing: Any) -> str:
        if listing.options and listing.variant_of:
            raise Blocked("INVALID_TARGET_KIND", "A listing cannot be both a family and a variant.")
        return (
            "ProductFamily"
            if listing.options
            else "Variant"
            if listing.variant_of
            else "SellableItem"
        )

    def contract(self, action_ref: str) -> dict:
        if action_ref not in self.actions:
            raise Blocked("UNKNOWN_ACTION", "Unknown ontology action.")
        return self.actions[action_ref]

    def related(self, listing: Any, merchant: str) -> list[dict]:
        kind = self.classify(listing)
        relations = [
            {
                "relation": "belongs_to_merchant",
                "source": listing.listing_id,
                "target": merchant,
                "merchant_id": merchant,
            }
        ]
        if kind == "Variant":
            relations.append(
                {
                    "relation": "variant_of",
                    "source": listing.listing_id,
                    "target": listing.variant_of,
                    "merchant_id": merchant,
                }
            )
        return relations


class ObservationAdapter:
    def __init__(self, store: Store, registry: OntologyRegistry, ttl: int):
        self.store, self.registry, self.ttl = store, registry, ttl

    def observe(
        self,
        task: TaskRecord,
        tool: str,
        result: Any,
        call_id: str,
        clock: datetime,
        metadata: dict,
    ) -> list[str]:
        evidence = []
        if tool == "get_pending_changes":
            coverage = Coverage(scope=task.merchant_id, **metadata.get("coverage", {}))
            pending = [c for c in result if c.status.value == "staged"]
            snapshot = PendingChangesSnapshot(
                task_id=task.task_id,
                merchant_id=task.merchant_id,
                change_ids=[c.change_id for c in pending],
                targets=[
                    i.target for c in pending if c.kind.value == "inventory_action" for i in c.items
                ],
                observed_at=clock,
                coverage=coverage,
            )
            self.store.put("pending", task.merchant_id, task.task_id, snapshot)
            return [snapshot.snapshot_id]
        if tool == "get_listing" and result is not None:
            kind = self.registry.classify(result)
            entity = EntityRef(
                merchant_id=task.merchant_id, object_type=kind, external_id=result.listing_id
            )
            snapshot = uid("snapshot")
            for field in ("stock", "sales_last_30d", "status", "variant_of", "options"):
                value = getattr(result, field)
                status = "known" if value is not None else "unknown"
                if field in {"stock", "sales_last_30d"} and value is not None:
                    if type(value) is not int or value < 0:
                        status = "invalid"
                    elif not metadata.get("valid_source", False):
                        status = "stale"
                    prior = [
                        o
                        for o in self.store.list("observations", task.merchant_id)
                        if o["task_id"] == task.task_id
                        and o["entity_ref"]["external_id"] == result.listing_id
                        and o["field"] == field
                        and o["source_revision"] is not None
                        and o["source_revision"] == metadata.get("revision")
                        and o["value_status"] in {"known", "conflicting"}
                    ]
                    if any(o["value"] != value for o in prior):
                        status = "conflicting"
                observation = Observation(
                    task_id=task.task_id,
                    merchant_id=task.merchant_id,
                    entity_ref=entity,
                    field=field,
                    value=value,
                    value_status=status,
                    unit="units" if field in {"stock", "sales_last_30d"} else None,
                    source_tool=tool,
                    tool_use_id=call_id,
                    observed_at=clock,
                    source_updated_at=metadata.get("source_updated_at"),
                    snapshot_id=snapshot,
                    source_revision=metadata.get("revision"),
                    coverage=Coverage(scope=result.listing_id, **metadata.get("coverage", {})),
                )
                self.store.put(
                    "observations", task.merchant_id, observation.observation_id, observation
                )
                evidence.append(observation.observation_id)
            self.store.put(
                "listings",
                task.merchant_id,
                f"{task.task_id}:{result.listing_id}",
                {
                    "kind": kind,
                    "listing_id": result.listing_id,
                    "relations": self.registry.related(result, task.merchant_id),
                    "observed_at": clock.isoformat(),
                    "snapshot_id": snapshot,
                },
            )
        if tool == "get_inventory_alerts":
            # Alert observations never call state.remember_listings.
            for alert in result:
                observation = Observation(
                    task_id=task.task_id,
                    merchant_id=task.merchant_id,
                    entity_ref=EntityRef(
                        merchant_id=task.merchant_id,
                        object_type="InventoryAlert",
                        external_id=uid("alert"),
                    ),
                    field="alert_for",
                    value=alert.listing_id,
                    value_status="known",
                    source_tool=tool,
                    tool_use_id=call_id,
                    observed_at=clock,
                    snapshot_id=uid("snapshot"),
                    coverage=Coverage(scope=task.merchant_id, **metadata.get("coverage", {})),
                )
                self.store.put(
                    "observations", task.merchant_id, observation.observation_id, observation
                )
                evidence.append(observation.observation_id)
            self.store.put(
                "alerts",
                task.merchant_id,
                task.task_id,
                {
                    "count": len(result),
                    "observed_at": clock.isoformat(),
                    "complete": metadata.get("coverage", {}).get("complete", False),
                },
            )
        return evidence

    def failed(self, task: TaskRecord, tool: str) -> None:
        if tool == "get_pending_changes":
            pending = self.store.get("pending", task.merchant_id, task.task_id)
            if pending:
                pending["current"] = False
                self.store.put("pending", task.merchant_id, task.task_id, pending)

    def view(self, task: TaskRecord, clock: datetime) -> dict:
        latest: dict[str, dict] = {}
        for raw in self.store.list("observations", task.merchant_id):
            if raw["task_id"] != task.task_id or raw["entity_ref"]["external_id"] != task.target:
                continue
            observation = Observation.model_validate(raw)
            if (clock - observation.observed_at).total_seconds() > self.ttl:
                observation.value_status = "stale"
            latest[observation.field] = observation.model_dump(mode="json")
        listing = self.store.get("listings", task.merchant_id, f"{task.task_id}:{task.target}")
        pending_raw = self.store.get("pending", task.merchant_id, task.task_id)
        pending = PendingChangesSnapshot.model_validate(pending_raw) if pending_raw else None
        current = bool(
            pending
            and pending.current
            and pending.coverage.complete
            and not pending.coverage.truncated
            and pending.coverage.scope == task.merchant_id
            and (clock - pending.observed_at).total_seconds() <= self.ttl
        )
        return {
            "listing": listing,
            "observations": latest,
            "pending": pending.model_dump(mode="json") if pending else None,
            "pending_current": current,
            "pending_present": task.target in pending.targets if current else None,
        }


def calculate_plan(
    task: TaskRecord, view: dict, clock: datetime, *, ttl: int, max_quantity: int
) -> RestockPlan:
    if not task.target or task.target_days is None:
        raise Blocked("MISSING_TASK_INPUT", "Specify one listing and target coverage days.")
    listing = view["listing"]
    if not listing:
        raise Blocked("MISSING_FULL_READ", "Read the full listing first.", ("ReadListing",))
    if listing["kind"] == "ProductFamily":
        raise Blocked("INVALID_TARGET_KIND", "Select a specific variant before restocking.")
    if not view["pending_current"]:
        raise Blocked(
            "INCOMPLETE_SNAPSHOT", "Read a complete current pending queue.", ("ReadPendingChanges",)
        )
    if view["pending_present"]:
        raise Blocked(
            "PENDING_CHANGE_CONFLICT",
            "Review the existing pending inventory change.",
            ("ReadPendingChanges",),
        )
    values = view["observations"]
    for field in ("stock", "sales_last_30d"):
        observation = values.get(field)
        if not observation or observation["value_status"] != "known":
            code = (
                "MISSING_SALES_HISTORY"
                if field == "sales_last_30d"
                and (not observation or observation["value_status"] == "unknown")
                else "STALE_OBSERVATION"
            )
            raise Blocked(code, f"{field} is missing, stale or invalid.", ("ReadListing",))
        if not observation["coverage"]["complete"] or observation["coverage"]["truncated"]:
            raise Blocked(
                "INCOMPLETE_SNAPSHOT", "Listing evidence is incomplete.", ("ReadListing",)
            )
    stock, sales = values["stock"]["value"], values["sales_last_30d"]["value"]
    if values["stock"]["snapshot_id"] != values["sales_last_30d"]["snapshot_id"]:
        raise Blocked(
            "STALE_OBSERVATION", "Inputs came from different snapshots.", ("ReadListing",)
        )
    revision = values["stock"]["source_revision"]
    if revision is None:
        raise Blocked("STALE_OBSERVATION", "The inventory revision is unknown.", ("ReadListing",))
    rate = Fraction(sales, 30)
    target = ceil(rate * task.target_days)
    quantity = max(0, target - stock)
    if quantity > max_quantity:
        raise Blocked(
            "GUARDRAIL_BLOCKED", "Quantity exceeds the restock limit; do not split or clamp it."
        )
    return RestockPlan(
        task_id=task.task_id,
        task_revision=task.revision,
        merchant_id=task.merchant_id,
        target=task.target,
        target_days=task.target_days,
        stock=stock,
        sales=sales,
        daily_rate=str(rate),
        target_stock=target,
        quantity=quantity,
        evidence_ids=[values[f]["observation_id"] for f in ("stock", "sales_last_30d")],
        input_digest=digest([stock, sales, task.target_days, revision]),
        target_revision=revision,
        pending_snapshot=view["pending"]["snapshot_id"],
        created_at=clock,
        expires_at=clock + timedelta(seconds=ttl),
        note="Zero sales do not support positive automatic replenishment." if sales == 0 else "",
    )
