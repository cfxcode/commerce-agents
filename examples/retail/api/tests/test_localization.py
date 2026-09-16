# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

import pytest

from commerce_common.streaming import AgentEvent
from demo_common.tests.fixtures import start_operator, start_shopper
from merchant_agent_runtime import MerchantAgent
from retail.api.localization import chinese_text
from shopping_agent import SearchFilters
from shopping_agent_runtime import ShoppingAgent


@pytest.mark.parametrize(
    ("path", "start", "agent_class"),
    [
        ("/api/chat", start_shopper, ShoppingAgent),
        ("/api/merchant/chat", start_operator, MerchantAgent),
    ],
)
def test_language_switch_keeps_the_session_and_reaches_the_agent(
    client, monkeypatch, path, start, agent_class
):
    contexts = []

    async def stream(_self, _messages, session, _state):
        contexts.append(session)
        yield AgentEvent.text_delta(
            "你好" if session.response_language == "Simplified Chinese" else "Hello"
        )
        yield AgentEvent(type="turn_complete")

    async def update_memory(*_args):
        return None

    monkeypatch.setattr(agent_class, "stream_turn", stream)
    monkeypatch.setattr(agent_class, "update_memory", update_memory)
    headers = start(client)
    for locale, expected in [("zh-CN", "Simplified Chinese"), ("en", "English")]:
        response = client.post(path, json={"message": "test", "locale": locale}, headers=headers)
        assert response.status_code == 200
        assert "turn_complete" in response.text
        assert contexts[-1].response_language == expected
    assert contexts[0].session_id == contexts[1].session_id
    assert (
        client.post(
            path, json={"message": "test", "locale": "invalid"}, headers=headers
        ).status_code
        == 422
    )
    assert len(contexts) == 2


async def test_every_localized_product_title_is_searchable(backend, session):
    for product in backend.products.values():
        results = await backend.search_products(session, chinese_text(product.title), limit=1)
        assert results and results[0].product_id == product.product_id


async def test_chinese_search_preserves_filters_and_finds_policies(backend, session):
    products = await backend.search_products(
        session, "家庭露营帐篷", SearchFilters(max_price=250, category="户外与露营")
    )
    assert products and all(product.price <= 250 for product in products)
    assert any(product.product_id == "AR-1202" for product in products)
    assert all(product.category == "outdoor-camping" for product in products)
    policies = await backend.search_policies(session, "帐篷退货退款政策")
    assert "returns" in {policy.policy_id for policy in policies}
    glass = await backend.search_products(
        session, "咖啡机", SearchFilters(attributes={"carafe": "玻璃"})
    )
    assert any(product.product_id == "AR-1001" for product in glass)
