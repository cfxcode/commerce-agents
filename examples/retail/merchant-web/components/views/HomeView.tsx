// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { useMemo, useState } from "react";
import {
  ApprovalsBanner,
  askWhy,
  AttentionList,
  AttentionRow,
  coverLabel,
  currentLocale,
  formatChangePct,
  formatComparisonLabel,
  formatDayMonth,
  formatMoney,
  formatNumber,
  formatPeriodLabel,
  formatRate,
  greeting,
  Icon,
  KindIcon,
  Notice,
  optionValuesLabel,
  PageHeader,
  Panel,
  Pill,
  plural,
  QueueOverflow,
  ratioChangePct,
  RecentChanges,
  RecordList,
  Segmented,
  Skeleton,
  StatStrip,
  StatTile,
  t,
  ViewLink,
} from "web-shared";
import { orderRows } from "@/lib/format";
import { INVENTORY_KINDS, ISSUE_KINDS } from "@/lib/kinds";
import type { HomeInsight, InventoryAlert, MetricPoint, OrderIssue, OverviewResponse } from "@/lib/types";

type Filter = "all" | "orders" | "stock" | "slow";
type Row = { kind: "issue"; issue: OrderIssue } | { kind: "inventory"; alert: InventoryAlert };

const ROW_CAP = 6;

/** One sentence from the overview: the sales move and what needs the operator. */
function briefing(data: OverviewResponse): string {
  const { snapshot, needs_attention } = data;
  const parts: string[] = [];
  if (snapshot.sales_change_pct != null) {
    const direction = snapshot.sales_change_pct >= 0 ? "up" : "down";
    parts.push(currentLocale() === "zh-CN" ? `本周销售额${direction === "up" ? "上升" : "下降"} ${formatChangePct(Math.abs(snapshot.sales_change_pct)).replace("+", "")}。` : `Sales are ${direction} ${formatChangePct(Math.abs(snapshot.sales_change_pct)).replace("+", "")} on the week.`);
  }
  const orders = needs_attention.order_issues.length;
  const listings = needs_attention.inventory.length;
  const needs = [orders ? plural(orders, "order") : "", listings ? plural(listings, "listing") : ""].filter(Boolean);
  parts.push(currentLocale() === "zh-CN" ? (orders || listings ? `今天有 ${orders} 个订单和 ${listings} 个商品需要关注。` : "今天没有需要处理的事项。") : (needs.length ? `${needs.join(" and ")} need you today.` : "Nothing needs you today."));
  return parts.join(" ");
}

function values(points?: MetricPoint[]): number[] | undefined {
  return points?.map((point) => point.value);
}

function rows(data: OverviewResponse, filter: Filter): Row[] {
  const { inventory, order_issues } = data.needs_attention;
  const issues = order_issues.map((issue) => ({ kind: "issue" as const, issue }));
  const lowStock = inventory
    .filter((alert) => alert.kind === "low_stock")
    .sort((a, b) => (a.days_of_cover ?? Infinity) - (b.days_of_cover ?? Infinity))
    .map((alert) => ({ kind: "inventory" as const, alert }));
  const slow = inventory.filter((alert) => alert.kind === "slow_mover").map((alert) => ({ kind: "inventory" as const, alert }));
  if (filter === "orders") return issues;
  if (filter === "stock") return lowStock;
  if (filter === "slow") return slow;
  // The most urgent stock alert leads; it is the one a seller acts on first.
  return [...lowStock.slice(0, 1), ...issues, ...lowStock.slice(1), ...slow];
}

function IssueRow({ issue, onAskAssistant }: { issue: OrderIssue; onAskAssistant: (text: string) => void }) {
  const style = ISSUE_KINDS[issue.kind];
  return (
    <AttentionRow
      icon={style.icon}
      tone={style.tone}
      title={issue.summary}
      meta={[t(style.label), currentLocale() === "zh-CN" ? `订单 ${issue.order_id}` : `Order ${issue.order_id}`, issue.opened_at ? (currentLocale() === "zh-CN" ? `${formatDayMonth(issue.opened_at)} 开启` : `opened ${formatDayMonth(issue.opened_at)}`) : ""].filter(Boolean).join(" · ")}
      action={{
        label: currentLocale() === "zh-CN" ? (issue.kind === "buyer_message" ? "起草回复" : "询问") : (issue.kind === "buyer_message" ? "Draft reply" : "Ask"),
        onClick: () => onAskAssistant(currentLocale() === "zh-CN" ? `订单 ${issue.order_id} 有哪些处理选项？${issue.summary}。` : `What are my options for order ${issue.order_id}? ${issue.summary}.`),
      }}
    />
  );
}

function InventoryRow({ alert, onAskAssistant }: { alert: InventoryAlert; onAskAssistant: (text: string) => void }) {
  const style = INVENTORY_KINDS[alert.kind];
  const soldOut = alert.kind === "low_stock" && alert.stock === 0;
  const low = alert.kind === "low_stock";
  const chosen = optionValuesLabel(alert);
  const name = chosen ? `${alert.title} · ${chosen}` : alert.title;
  const ref = `${name} (${alert.listing_id})`;
  return (
    <AttentionRow
      icon={style.icon}
      tone={soldOut ? "danger" : style.tone}
      title={name}
      meta={
        <>
          <span className={soldOut ? "font-semibold text-(--danger)" : low ? "font-semibold text-(--warn)" : ""}>
            {soldOut ? t("Sold out") : currentLocale() === "zh-CN" ? `库存 ${formatNumber(alert.stock)} 件` : `${formatNumber(alert.stock)} in stock`}
          </span>
          {[
            "",
            alert.days_of_cover != null && !soldOut ? coverLabel(alert.days_of_cover) : "",
            alert.sales_last_30d != null ? (currentLocale() === "zh-CN" ? `30 天售出 ${formatNumber(alert.sales_last_30d)} 件` : `${formatNumber(alert.sales_last_30d)} sold in 30 days`) : "",
            alert.listing_id,
            soldOut && alert.storefront_visible === false ? (currentLocale() === "zh-CN" ? "已从商城隐藏" : "hidden from the storefront") : "",
          ]
            .filter((part, index) => index === 0 || part)
            .join(" · ")}
        </>
      }
      note={
        // A paused listing still alerts here but shows no chip to shoppers.
        low && alert.stock > 0 && alert.storefront_visible ? (
          <Pill tone="warn" dot>
            {currentLocale() === "zh-CN" ? `商城显示“仅剩 ${formatNumber(alert.stock)} 件”` : `Storefront shows “Only ${formatNumber(alert.stock)} left”`}
          </Pill>
        ) : null
      }
      action={{
        label: currentLocale() === "zh-CN" ? (low ? "起草补货" : "计划降价") : (low ? "Draft restock" : "Plan markdown"),
        onClick: () => onAskAssistant(currentLocale() === "zh-CN" ? (low ? `为 ${ref} 起草补货方案。` : `为 ${ref} 制定降价方案。`) : (low ? `Draft a restock plan for ${ref}.` : `Plan a markdown for ${ref}.`)),
      }}
    />
  );
}

function Insights({ insights, onAskAssistant }: { insights: HomeInsight[]; onAskAssistant: (text: string) => void }) {
  if (insights.length === 0) return null;
  return (
    <Panel title={currentLocale() === "zh-CN" ? "助手建议" : "From the assistant"} icon={<KindIcon icon="spark" tone="accent" size={24} />}>
      <ul className="divide-y divide-(--line)">
        {insights.map((insight) => (
          <li key={insight.insight_id} className="px-[18px] py-2.5">
            <div className="text-[13px] font-medium leading-snug text-(--ink)">{insight.headline}</div>
            {insight.detail ? <div className="mt-0.5 line-clamp-2 text-[12px] leading-snug text-(--ink-soft)">{insight.detail}</div> : null}
            <button
              type="button"
              onClick={() => onAskAssistant(insight.prompt)}
              className="mt-1.5 inline-flex items-center gap-1 text-[12.5px] font-semibold text-(--accent-ink) hover:underline"
            >
              {currentLocale() === "zh-CN" ? "询问" : "Ask"} <Icon name="arrow-right" size={13} />
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export default function HomeView({
  data,
  failed,
  operator,
  onAskAssistant,
  onNavigate,
}: {
  data: OverviewResponse | null;
  failed: boolean;
  operator?: string;
  /** Prefills the composer; nothing is sent. */
  onAskAssistant: (text: string) => void;
  onNavigate: (view: "orders" | "inventory") => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const pending = useMemo(() => (data?.needs_attention.pending_changes ?? []).filter((change) => change.status === "staged"), [data]);
  const queue = useMemo(() => (data ? rows(data, filter) : []), [data, filter]);
  const now = useMemo(() => new Date(), []);
  const title = `${greeting(now)}${operator ? `, ${operator}` : ""}`;
  const today = now.toLocaleDateString(currentLocale() === "zh-CN" ? "zh-CN" : "en-US", { weekday: "long", month: "long", day: "numeric" });

  if (failed && !data) {
    return (
      <>
        <PageHeader title={title} subtitle={today} />
        <Notice>
          {currentLocale() === "zh-CN" ? "无法连接 8000 端口的商家 API。请运行 " : "The merchant API on port 8000 isn't reachable. Start it with "}
          <code className="rounded bg-(--well) px-1 font-mono text-[13px]">uvicorn retail.api.main:app --app-dir examples --port 8000</code>{currentLocale() === "zh-CN" ? " 后刷新页面。" : " and reload."}
        </Notice>
      </>
    );
  }
  if (!data) {
    return (
      <>
        <PageHeader title={title} subtitle={today} />
        <Skeleton className="h-36" />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
          <Skeleton className="h-96" />
          <Skeleton className="h-72" />
        </div>
      </>
    );
  }

  const { snapshot } = data;
  const counts = {
    orders: data.needs_attention.order_issues.length,
    stock: data.needs_attention.inventory.filter((alert) => alert.kind === "low_stock").length,
    slow: data.needs_attention.inventory.filter((alert) => alert.kind === "slow_mover").length,
  };
  const comparison = formatComparisonLabel(snapshot.period, snapshot.compare_to);
  // The snapshot carries no average-order delta, so derive it from the sales and orders deltas.
  const aovChangePct = ratioChangePct(snapshot.sales_change_pct, snapshot.orders_change_pct);
  const currency = snapshot.currency ?? "USD";

  return (
    <div className="ac-reveal flex flex-col gap-5">
      <PageHeader title={title} subtitle={`${today} · ${briefing(data)}`} />

      <ApprovalsBanner changes={pending} onReview={() => onAskAssistant(currentLocale() === "zh-CN" ? "逐项说明等待我批准的更改及其影响。" : "Walk me through the changes awaiting my approval and what each one would do.")} />

      <Panel title={currentLocale() === "zh-CN" ? "本周" : "This week"} subtitle={`${formatPeriodLabel(snapshot.period)}${comparison ? (currentLocale() === "zh-CN" ? ` · 对比${comparison}` : ` · against the ${comparison}`) : ""}`} bodyClassName="pb-1">
        <StatStrip>
          <StatTile
            label={t("Sales")}
            value={formatMoney(snapshot.sales, currency, { whole: snapshot.sales >= 1000 })}
            changePct={snapshot.sales_change_pct}
            points={values(data.trends?.sales)}
            prior={values(data.trends_prior?.sales)}
            onClick={() => onAskAssistant(askWhy("Sales", snapshot.sales_change_pct, comparison))}
            ariaLabel="Sales: ask the assistant why"
          />
          <StatTile
            label={t("Orders")}
            value={formatNumber(snapshot.orders)}
            changePct={snapshot.orders_change_pct}
            points={values(data.trends?.orders)}
            prior={values(data.trends_prior?.orders)}
            onClick={() => onAskAssistant(askWhy("Orders", snapshot.orders_change_pct, comparison))}
            ariaLabel="Orders: ask the assistant why"
          />
          <StatTile
            label={t("Conversion")}
            value={snapshot.conversion_rate != null ? formatRate(snapshot.conversion_rate) : "—"}
            changePct={snapshot.conversion_change_pct}
            points={values(data.trends?.conversion)}
            prior={values(data.trends_prior?.conversion)}
            onClick={() => onAskAssistant(askWhy("Conversion", snapshot.conversion_change_pct, comparison))}
            ariaLabel="Conversion: ask the assistant why"
          />
          <StatTile
            label={currentLocale() === "zh-CN" ? "平均订单金额" : "Average order"}
            value={snapshot.average_order_value != null ? formatMoney(snapshot.average_order_value, currency) : "—"}
            changePct={aovChangePct}
            points={values(data.trends?.average_order_value)}
            prior={values(data.trends_prior?.average_order_value)}
            onClick={() => onAskAssistant(askWhy("Average order value", aovChangePct, comparison))}
            ariaLabel="Average order value: ask the assistant why"
          />
        </StatStrip>
      </Panel>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <Panel
          title={currentLocale() === "zh-CN" ? "今天需要关注" : "Needs you today"}
          action={
            <Segmented<Filter>
              label={currentLocale() === "zh-CN" ? "筛选关注事项" : "Filter attention items"}
              value={filter}
              onChange={setFilter}
              options={[
                { id: "all", label: t("All"), count: counts.orders + counts.stock + counts.slow },
                { id: "orders", label: t("Orders"), count: counts.orders },
                { id: "stock", label: t("Low stock"), count: counts.stock },
                { id: "slow", label: currentLocale() === "zh-CN" ? "滞销" : "Slow", count: counts.slow },
              ]}
            />
          }
        >
          {queue.length === 0 ? (
            <p className="px-[18px] pb-4 pt-1 text-[13.5px] text-(--ink-soft)">{currentLocale() === "zh-CN" ? "今天没有需要处理的事项。" : "Nothing needs you today."}</p>
          ) : (
            <>
              <AttentionList>
                {queue.slice(0, ROW_CAP).map((row) =>
                  row.kind === "issue" ? (
                    <IssueRow key={row.issue.issue_id} issue={row.issue} onAskAssistant={onAskAssistant} />
                  ) : (
                    <InventoryRow key={`${row.alert.kind}-${row.alert.listing_id}`} alert={row.alert} onAskAssistant={onAskAssistant} />
                  ),
                )}
              </AttentionList>
              <QueueOverflow
                hidden={queue.length - ROW_CAP}
                link={{
                  label: currentLocale() === "zh-CN" ? "查看全部" : "See all",
                  // The hidden rows are order issues first, so open Orders when any of them is one.
                  onClick: () => onNavigate(queue.slice(ROW_CAP).some((row) => row.kind === "issue") ? "orders" : "inventory"),
                }}
              />
            </>
          )}
        </Panel>

        <div className="flex flex-col gap-4">
          <Insights insights={data.insights ?? []} onAskAssistant={onAskAssistant} />
          <Panel title={t("Recent orders")} action={<ViewLink label={currentLocale() === "zh-CN" ? "全部订单" : "All orders"} onClick={() => onNavigate("orders")} />}>
            {data.recent_orders.length === 0 ? (
              <p className="px-[18px] pb-4 text-[13px] text-(--ink-soft)">{currentLocale() === "zh-CN" ? "暂无订单。" : "No orders yet."}</p>
            ) : (
              <RecordList rows={orderRows(data.recent_orders.slice(0, 4))} />
            )}
          </Panel>
          <RecentChanges changes={data.recent_changes} />
        </div>
      </div>
    </div>
  );
}
