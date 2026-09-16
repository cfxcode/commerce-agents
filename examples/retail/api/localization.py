# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Static fixture translations and bilingual keyword search; ids stay canonical."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

_CJK = re.compile(r"[\u3400-\u9fff]+")
_SEARCH_TERMS = {
    "退货": "returns",
    "退款": "refunds",
    "配送": "shipping",
    "运费": "shipping",
    "送货": "shipping",
    "保修": "warranty",
    "会员": "membership",
    "礼品卡": "gift cards",
    "取消订单": "cancelling order",
    "修改订单": "changing order",
    "损坏": "damaged",
    "缺失": "missing",
    "帐篷": "tent",
    "露营": "camping",
    "家庭": "family",
    "背包": "backpack",
    "睡袋": "sleeping bag",
    "咖啡": "coffee",
    "滴滤": "drip",
    "意式": "espresso",
    "书桌": "desk",
    "办公桌": "desk",
    "办公椅": "chair",
    "显示器": "monitor",
    "键盘": "keyboard",
    "耳机": "headphones",
    "床垫": "mattress",
    "床架": "bed frame",
    "枕头": "pillow",
    "瑜伽": "yoga",
    "哑铃": "dumbbell",
    "宠物": "pet",
    "狗床": "dog bed",
    "猫": "cat",
    "儿童": "kids",
    "玩具": "toys",
    "拼图": "puzzle",
    "海洋": "ocean",
    "海底": "ocean",
    "墙贴": "decals",
    "行李箱": "suitcase",
    "旅行": "travel",
    "保湿": "moisturizer",
    "精华": "serum",
}
_STOP_BIGRAMS = {
    "请推",
    "推荐",
    "帮我",
    "我想",
    "想要",
    "可以",
    "一下",
    "商品",
    "寻找",
    "需要",
    "适合",
    "一个",
    "一款",
    "预算",
    "美元",
    "以内",
}
_CATEGORIES = {
    "家居与厨房": "home-kitchen",
    "户外与露营": "outdoor-camping",
    "办公与电子产品": "office-electronics",
    "家具与卧室": "furniture-bedroom",
    "美妆与个护": "beauty-personal-care",
    "健身": "fitness",
    "儿童房": "kids-room",
    "食品杂货": "grocery",
    "宠物用品": "pet-supplies",
    "玩具与游戏": "toys-games",
    "旅行": "travel",
}


def canonical_category(value: str) -> str:
    return _CATEGORIES.get(value, value)


@lru_cache(maxsize=1)
def translations() -> dict[str, str]:
    return json.loads((Path(__file__).parents[1] / "data/locales/zh-CN.json").read_text())


def chinese_text(text: str) -> str:
    return translations().get(text, text)


def search_query(query: str) -> str:
    if not _CJK.search(query):
        return query
    # An exact localized fixture title is a precise lookup, not a bag of common words.
    exact = next(
        (source for source, target in translations().items() if target == query.strip()), None
    )
    if exact:
        return exact
    terms = [english for chinese, english in _SEARCH_TERMS.items() if chinese in query]
    return f"{query} {' '.join(terms)} localized"


def chinese_score(fields: Mapping[str, str], weights: Mapping[str, float], query: str) -> float:
    terms = {
        part[index : index + 2] for part in _CJK.findall(query) for index in range(len(part) - 1)
    } - _STOP_BIGRAMS
    if not terms:
        return 0.0
    localized = {field: chinese_text(text) for field, text in fields.items()}
    return sum(
        max(
            (weights.get(field, 1.0) for field, text in localized.items() if term in text),
            default=0.0,
        )
        for term in terms
    )
