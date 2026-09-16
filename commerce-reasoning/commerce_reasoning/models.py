"""Provider-independent task, evidence, execution and guidance contracts."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def now() -> datetime:
    return datetime.now(UTC)


def digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def change_digest(change: Any) -> str:
    return digest(
        {
            "change_id": change.change_id,
            "kind": change.kind.value,
            "summary": change.summary,
            "items": [item.model_dump(mode="json") for item in change.items],
        }
    )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityRef(StrictModel):
    merchant_id: str
    object_type: str
    external_id: str


class Coverage(StrictModel):
    scope: str
    complete: bool = False
    truncated: bool = False
    reason: str | None = None


class Observation(StrictModel):
    observation_id: str = Field(default_factory=lambda: uid("obs"))
    task_id: str
    merchant_id: str
    entity_ref: EntityRef
    field: str
    value: Any = None
    value_status: Literal["known", "unknown", "stale", "invalid", "conflicting"] = "unknown"
    unit: str | None = None
    source_tool: str
    tool_use_id: str
    observed_at: datetime
    source_updated_at: datetime | None = None
    snapshot_id: str
    source_revision: int | None = None
    coverage: Coverage
    trust_class: Literal["structured", "untrusted_text", "host"] = "structured"


class TaskRecord(StrictModel):
    task_id: str = Field(default_factory=lambda: uid("task"))
    merchant_id: str
    operator: str
    session_hash: str
    environment_id: str
    revision: int = 1
    target: str | None = None
    target_days: int | None = Field(default=None, ge=1, le=365)
    intent: Literal["restock", "check_only", "unrelated"] = "restock"
    phase: str = "START"
    host_outcome: Literal["applied", "discarded", "unknown"] | None = None
    release_id: str = "development"
    knowledge_hash: str = ""
    turn_id: str = Field(default_factory=lambda: uid("turn"))
    unknowns: list[str] = Field(default_factory=list)
    recovery_reads: int = 0
    created_at: datetime
    updated_at: datetime


class PendingChangesSnapshot(StrictModel):
    snapshot_id: str = Field(default_factory=lambda: uid("pending"))
    task_id: str
    merchant_id: str
    change_ids: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    observed_at: datetime
    coverage: Coverage
    current: bool = True


class RestockPlan(StrictModel):
    plan_id: str = Field(default_factory=lambda: uid("plan"))
    task_id: str
    task_revision: int
    merchant_id: str
    target: str
    target_days: int
    stock: int
    sales: int
    daily_rate: str
    target_stock: int
    quantity: int
    formula_version: str = "cover_days_v1"
    evidence_ids: list[str]
    input_digest: str
    target_revision: int
    pending_snapshot: str
    created_at: datetime
    expires_at: datetime
    status: Literal["valid", "stale", "superseded", "consumed"] = "valid"
    note: str = ""


class ExecutionContext(StrictModel):
    merchant_id: str
    operator: str
    session_hash: str
    task_id: str
    turn_id: str
    request_id: str
    origin: Literal["agent", "host"]


class ApprovalRecord(StrictModel):
    approval_id: str = Field(default_factory=lambda: uid("approval"))
    merchant_id: str
    task_id: str
    operator: str
    change_id: str
    payload_digest: str
    target_revision: int | None = None
    expires_at: datetime
    consumed: bool = False


class ActionReceipt(StrictModel):
    merchant_id: str
    change_id: str
    payload_digest: str
    status: Literal[
        "not_started", "in_progress", "succeeded", "failed_no_effect", "outcome_unknown"
    ]
    before: dict[str, int] = Field(default_factory=dict)
    after: dict[str, int] = Field(default_factory=dict)
    revisions: dict[str, int] = Field(default_factory=dict)
    applied_at: datetime | None = None


class Guidance(StrictModel):
    immediate_goal: str = Field(max_length=400)
    recommended_action_refs: list[str] = Field(default_factory=list, max_length=5)
    required_evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    unknowns: list[str] = Field(default_factory=list, max_length=10)
    cautions: list[str] = Field(default_factory=list, max_length=10)
    used_edge_ids: list[str] = Field(default_factory=list, max_length=10)
    stop_or_wait_reason: str | None = Field(default=None, max_length=400)


class Blocked(Exception):
    def __init__(
        self, code: str, reason: str, reads: tuple[str, ...] = (), evidence: tuple[str, ...] = ()
    ):
        super().__init__(reason)
        self.code, self.reason, self.reads, self.evidence = code, reason, reads, evidence

    def payload(self) -> dict:
        return {
            "status": "blocked",
            "error_code": self.code,
            "reason": self.reason,
            "required_reads": self.reads,
            "evidence_refs": self.evidence,
            "retryable_without_new_evidence": False,
        }
