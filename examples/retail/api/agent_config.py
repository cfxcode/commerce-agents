# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""The ACME retail deployment's two agent configs; the only place this example reads
deployment knobs from the environment."""

from __future__ import annotations

import os

from demo_common import host_approval_default
from merchant_agent import MerchantAgentConfig
from shopping_agent import ShoppingAgentConfig


def build_reasoning_config():
    from commerce_reasoning import ReasoningConfig
    from demo_common import REPO_ROOT

    path = REPO_ROOT / os.environ.get("COMMERCE_REASONING_CONFIG", "configs/reasoning.yaml")
    config = ReasoningConfig.from_file(path) if path.exists() else ReasoningConfig()
    if os.environ.get("COMMERCE_REASONING_ENABLED") is not None:
        config.enabled = os.environ["COMMERCE_REASONING_ENABLED"] == "1"
    return config


def _model_settings() -> dict[str, str]:
    """Allow local Anthropic-compatible gateways to override the demo models."""
    model = os.environ.get("COMMERCE_MODEL")
    if not model:
        return {}
    return {
        "model": model,
        "memory_model": os.environ.get("COMMERCE_MEMORY_MODEL", model),
    }


def build_shopping_config() -> ShoppingAgentConfig:
    return ShoppingAgentConfig(
        brand_name="ACME",
        assistant_name="ACME Assistant",
        brand_voice="professional, warm, and brief",
        **_model_settings(),
    )


def build_merchant_config(store_name: str) -> MerchantAgentConfig:
    return MerchantAgentConfig(
        brand_name=store_name,
        require_host_approval=host_approval_default(),
        approval_surface="the Approve button on the change preview card",
        # This deployment runs the run_analysis delegate over MockRetailMerchant's
        # read-only SQL view of the fixtures. MERCHANT_ANALYSIS_CODE_EXECUTION=1 adds the
        # code-execution sandbox (first-party API only); MERCHANT_ANALYSIS_MODEL overrides
        # the delegate's model, which otherwise inherits the main one.
        enable_analysis=True,
        analysis_use_code_execution=os.environ.get("MERCHANT_ANALYSIS_CODE_EXECUTION", "0") == "1",
        analysis_model=os.environ.get("MERCHANT_ANALYSIS_MODEL") or None,
        **_model_settings(),
    )
