# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Live retail bilingual smoke check against a running demo API. Needs model credentials.

python scripts/smoke_retail_i18n.py --url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any

import httpx

CHINESE = re.compile(r"[\u3400-\u9fff]")


def parse_events(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    kind = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            kind = line[7:]
        elif line.startswith("data: ") and kind:
            events.append((kind, json.loads(line[6:])))
    return events


async def turn(
    client: httpx.AsyncClient, path: str, session: str, message: str, locale: str = "zh-CN"
) -> set[str]:
    response = await client.post(
        path, headers={"X-Session-Id": session}, json={"message": message, "locale": locale}
    )
    response.raise_for_status()
    events = parse_events(response.text)
    errors = [data for kind, data in events if kind == "error"]
    assert not errors, errors
    assert any(kind == "turn_complete" for kind, _ in events)
    text = "".join(data.get("text", "") for kind, data in events if kind == "text_delta")
    tools = {data["tool"] for kind, data in events if kind == "tool_call"}
    ui = [data for kind, data in events if kind == "ui"]
    if locale == "zh-CN":
        generated = text + json.dumps(
            [data["payload"] for data in ui if data["component"] == "suggestions"],
            ensure_ascii=False,
        )
        assert CHINESE.search(generated), "reply has no Chinese text"
    else:
        assert text and not CHINESE.search(text), "selected English locale was not respected"
    print(f"{path} {locale}: {sorted(tools)}; UI {[data['component'] for data in ui]}", flush=True)
    print(text[:220], flush=True)
    return tools


async def run(url: str) -> None:
    async with httpx.AsyncClient(base_url=url, timeout=180, trust_env=False) as client:
        session = (await client.post("/api/session", json={"user_id": "demo-user"})).json()[
            "session_id"
        ]
        assert "search_products" in await turn(
            client, "/api/chat", session, "推荐两款250美元以内的露营帐篷。"
        )
        assert "present_comparison" in await turn(
            client, "/api/chat", session, "比较 AR-1201 和 AR-1202 的空间和搭建难度。"
        )
        assert "add_to_cart" in await turn(
            client, "/api/chat", session, "将 AR-1202 家庭款加入购物车，并告诉我退货政策。"
        )
        await turn(client, "/api/chat", session, "谢谢，就这些。", "en")
        merchant = (await client.post("/api/merchant/session")).json()["session_id"]
        await turn(client, "/api/merchant/chat", merchant, "今天早上有哪些事项需要我关注？")
        tools = await turn(
            client,
            "/api/merchant/chat",
            merchant,
            "请分析过去两周销售额的变化，按儿童房与其他商品拆分贡献，比较本周与上周并给出数据支持的结论。",
        )
        assert "run_analysis" in tools, "the analysis delegate was not exercised"
    print("Bilingual live conversation checks passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    asyncio.run(run(parser.parse_args().url))
