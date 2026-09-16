"""Single-process atomic retail simulation with revisions and effect receipts.

Business state remains in memory. A process restart creates a new environment; old
sidecars are audit only. No cross-process transaction guarantee is implied.
"""

import asyncio
import copy
import functools
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime
from typing import Any

from commerce_reasoning.models import ActionReceipt, Blocked, change_digest, now
from merchant_agent import ChangeKind, ChangeLedger, ChangeStatus

from .mock_merchant import MockRetailMerchant


class ReasoningRetailMerchant(MockRetailMerchant):
    def __init__(self, *args: Any, clock: Callable[[], datetime] = now, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.clock = clock
        self.ledger = ChangeLedger(self.config, clock=clock)
        self.commit_lock = asyncio.Lock()
        self.revisions: dict[str, int] = {}
        self.change_revisions: dict[str, dict[str, int]] = {}
        self.receipts: dict[str, ActionReceipt] = {}
        self.pending_coverage = {"complete": True, "truncated": False}
        self.valid_source = True
        self.fail_commit = False
        self.unknown_after_commit = False
        self.write_expectations = ContextVar("retail_write_expectations", default=None)

    def check_scope(self, session: Any) -> None:
        if session.merchant_id != self.merchant_id:
            raise Blocked("TENANT_SCOPE_MISMATCH", "Merchant scope does not match this backend.")

    def revision(self, target: str) -> int:
        return self.revisions.get(target, 1)

    def observation_metadata(self, tool: str, target: str | None = None) -> dict:
        return {
            "revision": self.revision(target) if target else None,
            "source_updated_at": None,  # Fixture validity is explicit, not invented source time.
            "valid_source": self.valid_source,
            "coverage": self.pending_coverage
            if tool == "get_pending_changes"
            else {"complete": True, "truncated": False},
        }

    async def get_listing(self, session, listing_id):
        self.check_scope(session)
        return await super().get_listing(session, listing_id)

    async def get_pending_changes(self, session):
        self.check_scope(session)
        return await super().get_pending_changes(session)

    async def get_inventory_alerts(self, session):
        self.check_scope(session)
        return await super().get_inventory_alerts(session)

    async def stage_inventory_action(self, session, items, note=None):
        self.check_scope(session)
        async with self.commit_lock:
            binding = self.write_expectations.get()
            plan = binding.get("plan") if binding else None
            if plan and (
                self.revision(plan.target) != plan.target_revision
                or int(self._state_row(plan.target)["stock"]) != plan.stock
                or len(items) != 1
                or items[0].quantity != plan.quantity
                or items[0].listing_id != plan.target
            ):
                raise Blocked("STALE_PLAN", "The plan changed before the atomic stage check.")
            targets = {
                self._product(i.listing_id).product_id
                if self._product(i.listing_id)
                else i.listing_id
                for i in items
            }
            for item in items:
                product = self._product(item.listing_id)
                if product and product.has_options and item.action in {"pause", "activate"}:
                    targets.update(variant.product_id for variant in product.variants)
            if any(
                target in targets
                for c in self.ledger.pending()
                if c.kind is ChangeKind.INVENTORY_ACTION
                for target in self.change_revisions.get(c.change_id, {i.target: 1 for i in c.items})
            ):
                raise Blocked(
                    "PENDING_CHANGE_CONFLICT",
                    "Another pending inventory change affects this target.",
                )
            staged = await super().stage_inventory_action(session, items, note)
            self.change_revisions[staged.change_id] = {
                target: self.revision(target) for target in targets
            }
            return staged

    async def discard_change(self, session, change_id, **kwargs):
        self.check_scope(session)
        async with self.commit_lock:
            return await super().discard_change(session, change_id, **kwargs)

    async def apply_change(self, session, change_id):
        self.check_scope(session)
        async with self.commit_lock:
            change = self.ledger.get(change_id)
            if change is None:
                raise Blocked("UNKNOWN_CHANGE", "The change does not exist.")
            fingerprint = change_digest(change)
            binding = self.write_expectations.get()
            if binding and binding.get("digest") != fingerprint:
                raise Blocked("APPROVAL_DIGEST_MISMATCH", "The payload changed before commit.")
            receipt = self.receipts.get(change_id)
            if receipt:
                if receipt.payload_digest != fingerprint:
                    raise Blocked("APPROVAL_DIGEST_MISMATCH", "The change payload was altered.")
                return change
            for target, revision in self.change_revisions.get(change_id, {}).items():
                if revision != self.revision(target):
                    raise Blocked(
                        "STALE_TARGET_REVISION",
                        "Inventory changed after preview; recalculate and approve again.",
                    )
            if change.status is not ChangeStatus.STAGED:
                raise Blocked("STAGED_STATUS", "Only staged changes can be applied.")
            # Copy one aggregate so catalog family/variant references stay shared.
            candidate = copy.copy(self)
            candidate.storefront = copy.copy(self.storefront)
            candidate.ledger, candidate._inventory, candidate._campaigns, products, variants = (
                copy.deepcopy(
                    (
                        self.ledger,
                        self._inventory,
                        self._campaigns,
                        self.storefront.products,
                        self.storefront.variants,
                    )
                )
            )
            candidate.storefront.products, candidate.storefront.variants = products, variants
            candidate.ledger._clock = self.clock
            before = {
                i.target: int(self._state_row(i.target)["stock"])
                for i in change.items
                if i.field == "stock"
            }
            applied = candidate.ledger.apply(change_id, actor=session.operator)
            candidate._apply_to_live_state(applied)
            if self.fail_commit:
                raise Blocked(
                    "FAILED_NO_EFFECT", "Injected inventory commit failure; no state was changed."
                )
            after = {target: int(candidate._state_row(target)["stock"]) for target in before}
            revisions = {
                target: self.revision(target) + 1
                for target in self.change_revisions.get(change_id, {})
            }
            receipt = ActionReceipt(
                merchant_id=session.merchant_id,
                change_id=change_id,
                payload_digest=fingerprint,
                status="succeeded",
                before=before,
                after=after,
                revisions=revisions,
                applied_at=self.clock(),
            )
            # No await between these swaps: one event-loop commit, receipt included.
            self.ledger, self._inventory, self._campaigns = (
                candidate.ledger,
                candidate._inventory,
                candidate._campaigns,
            )
            self.storefront.products, self.storefront.variants = products, variants
            self.revisions.update(revisions)
            self.receipts[change_id] = receipt
            if self.unknown_after_commit:
                raise TimeoutError("Injected lost response after commit")
            return applied


def _scoped(name):
    original = getattr(MockRetailMerchant, name)

    @functools.wraps(original)
    async def method(self, session, *args, **kwargs):
        self.check_scope(session)
        return await original(self, session, *args, **kwargs)

    return method


# The remaining inherited boundaries also check their trusted session, including
# read-only analysis and methods that the portal calls without the tool executor.
for _method in (
    "get_business_snapshot",
    "query_metrics",
    "get_campaign_performance",
    "search_listings",
    "get_order_issues",
    "get_pricing_context",
    "stage_listing_update",
    "stage_price_update",
    "stage_promotion",
    "stage_campaign",
    "get_analysis_schema",
    "execute_analysis_query",
    "get_merchant_context",
):
    setattr(ReasoningRetailMerchant, _method, _scoped(_method))
