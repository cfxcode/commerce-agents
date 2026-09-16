// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { AssistantPanel as PanelShell, currentLocale, type MerchantChat, type Prefill } from "web-shared";
import type { StagedChange } from "@/lib/types";
import GenerativeBlock from "./generative";

function copy() {
  return currentLocale() === "zh-CN"
    ? {
        title: "商家助手",
        intro: "可以询问经营表现、库存、定价或营销活动。",
        starters: ["今天早上有哪些事项需要我关注？", "本周销售额与上周相比如何？", "哪些商品库存不足？", "哪些滞销商品适合降价？"],
        label: "向商家助手发送消息",
        placeholder: "询问销售、库存或定价…",
      }
    : {
        title: "Merchant assistant",
        intro: "Ask about performance, inventory, pricing, or campaigns.",
        starters: ["What needs my attention this morning?", "How did sales do this week compared to last?", "Which listings are running low on stock?", "Which slow movers should we mark down?"],
        label: "Message the merchant assistant",
        placeholder: "Ask about sales, stock, pricing…",
      };
}

export default function AssistantPanel({
  chat,
  prefill,
  onPrefill,
  ...shell
}: {
  chat: MerchantChat<StagedChange>;
  prefill: Prefill | null;
  onPrefill: (text: string) => void;
  newMemoryCount: number;
  onOpenActivity: () => void;
  onClose: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
}) {
  return (
    <PanelShell
      chat={chat}
      copy={copy()}
      prefill={prefill}
      renderBlock={(segment) => (
        <GenerativeBlock
          block={segment.block}
          status={segment.status}
          onChangeAction={chat.actOnChange}
          onPrefill={onPrefill}
        />
      )}
      {...shell}
    />
  );
}
