// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { AttentionList, AttentionRow, currentLocale, formatDayMonth, Notice, PageHeader, Panel, plural, QuotedAsData, RecordList, Skeleton, t, useResource } from "web-shared";
import { fetchAlerts } from "@/lib/api";
import { orderRows } from "@/lib/format";
import { ISSUE_KINDS } from "@/lib/kinds";
import type { OrderIssue, RecentOrder } from "@/lib/types";

function IssueRow({ issue, onAskAssistant }: { issue: OrderIssue; onAskAssistant: (text: string) => void }) {
  const style = ISSUE_KINDS[issue.kind];
  return (
    <AttentionRow
      icon={style.icon}
      tone={style.tone}
      title={issue.summary}
      meta={[t(style.label), currentLocale() === "zh-CN" ? `订单 ${issue.order_id}` : `Order ${issue.order_id}`, issue.listing_id ?? "", issue.opened_at ? (currentLocale() === "zh-CN" ? `${formatDayMonth(issue.opened_at)} 开启` : `opened ${formatDayMonth(issue.opened_at)}`) : ""].filter(Boolean).join(" · ")}
      note={
        issue.buyer_message_excerpt ? (
          <div className="mt-1 rounded-[10px] bg-(--ground) px-3 py-2">
            <blockquote className="text-[13px] leading-snug text-(--ink-2)">&ldquo;{issue.buyer_message_excerpt}&rdquo;</blockquote>
            {/* Some fixture excerpts are injection attempts, so the note sits beside the quote. */}
            <QuotedAsData subject={currentLocale() === "zh-CN" ? "买家消息" : "Buyer message"} className="mt-1.5" />
          </div>
        ) : null
      }
      action={{
        label: currentLocale() === "zh-CN" ? (issue.kind === "buyer_message" ? "起草回复" : "询问") : (issue.kind === "buyer_message" ? "Draft reply" : "Ask"),
        onClick: () => onAskAssistant(currentLocale() === "zh-CN" ? `订单 ${issue.order_id} 有哪些处理选项？${issue.summary}。` : `What are my options for order ${issue.order_id}? ${issue.summary}.`),
      }}
    />
  );
}

export default function OrdersView({
  refreshKey,
  recentOrders,
  onAskAssistant,
}: {
  refreshKey: number;
  recentOrders: RecentOrder[] | null;
  onAskAssistant: (text: string) => void;
}) {
  const { data, failed } = useResource(fetchAlerts, [refreshKey]);
  const issues = data?.order_issues ?? [];

  return (
    <div className="ac-reveal flex flex-col gap-4">
      <PageHeader title={t("Orders")} subtitle={data ? (currentLocale() === "zh-CN" ? (issues.length ? `${issues.length} 个未解决问题` : "没有未解决问题") : (issues.length ? plural(issues.length, "open issue") : "No open issues")) : undefined} />
      {failed && !data ? (
        <Notice>{currentLocale() === "zh-CN" ? "无法连接商家 API，因此无法加载订单问题。" : "The merchant API isn't reachable, so order issues can't load."}</Notice>
      ) : !data ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <Skeleton className="h-96" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <Panel title={currentLocale() === "zh-CN" ? "未解决问题" : "Open issues"} subtitle={issues.length ? String(issues.length) : undefined}>
            {issues.length === 0 ? (
              <p className="px-[18px] pb-4 text-[13.5px] text-(--ink-soft)">{currentLocale() === "zh-CN" ? "没有未解决的订单问题。" : "No open order issues."}</p>
            ) : (
              <AttentionList>
                {issues.map((issue) => (
                  <IssueRow key={issue.issue_id} issue={issue} onAskAssistant={onAskAssistant} />
                ))}
              </AttentionList>
            )}
          </Panel>
          <Panel title={t("Recent orders")}>
            {!recentOrders ? (
              <Skeleton className="mx-[18px] mb-4 h-40" />
            ) : recentOrders.length === 0 ? (
              <p className="px-[18px] pb-4 text-[13px] text-(--ink-soft)">{currentLocale() === "zh-CN" ? "没有可显示的最近订单。" : "No recent orders to show."}</p>
            ) : (
              <RecordList rows={orderRows(recentOrders)} />
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}
