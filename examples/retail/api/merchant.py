# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""The ACME retail merchant router: the shared portal routes over ``MockRetailMerchant``,
plus the KPI trends and insight cards the retail portal's home page shows."""

from __future__ import annotations

from fastapi import APIRouter

from commerce_common.memory import MemoryStore
from commerce_reasoning.execution import MerchantExecutionService
from demo_common import REPO_ROOT, MerchantIdentity, build_merchant_router
from merchant_agent_runtime import MerchantAgent

from .agent_config import build_merchant_config, build_reasoning_config
from .mock_retail import MockRetail
from .reasoning_backend import ReasoningRetailMerchant

IDENTITY = MerchantIdentity(merchant_id="acme-retail", operator="Avery")


def create_merchant_router(storefront: MockRetail, memory_store: MemoryStore) -> APIRouter:
    config = build_merchant_config(storefront.store_name)
    config.require_host_approval = True
    merchant = ReasoningRetailMerchant(storefront, config, merchant_id=IDENTITY.merchant_id)
    service = MerchantExecutionService(
        backend=merchant, root=REPO_ROOT, config=build_reasoning_config()
    )
    agent = MerchantAgent(
        backend=merchant,
        skills_dir=REPO_ROOT / "merchant-agent" / "skills",
        config=config,
        memory_store=memory_store,
        execution_service=service,
    )
    return build_merchant_router(
        storefront=storefront,
        backend=merchant,
        agent=agent,
        identity=IDENTITY,
        example_dir="retail",
        overview_extras=lambda: {
            "trends": merchant.kpi_trends(),
            "trends_prior": merchant.kpi_trends(periods_back=1),
            "insights": merchant.home_insights(),
        },
    )
