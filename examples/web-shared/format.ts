// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import { currentLocale, t } from "./i18n-core";

const moneyFormatters = new Map<string, Intl.NumberFormat>();

function intlLocale(): string {
  return currentLocale() === "zh-CN" ? "zh-CN" : "en-US";
}

export function formatMoney(
  value: number,
  currency = "USD",
  options: { whole?: boolean } = {},
): string {
  const key = `${intlLocale()}:${currency}:${options.whole ? 0 : 2}`;
  let formatter = moneyFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(intlLocale(), {
      style: "currency",
      currency,
      maximumFractionDigits: options.whole ? 0 : 2,
    });
    moneyFormatters.set(key, formatter);
  }
  return formatter.format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat(intlLocale()).format(value);
}

/** Rates arrive as percent values (3.4 means 3.4%). */
export function formatRate(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function formatChangePct(value: number): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

/** Date-only strings parse as local midnight so they do not render a day early. */
function parseDate(value: string): Date {
  return new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value);
}

const ISO_DAY = /\d{4}-\d{2}-\d{2}/g;

function dayLabel(value: string): string {
  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(intlLocale(), { month: "short", day: "numeric", year: "numeric" });
}

/** "Jun 24, 2026"; dates inside a trailing note ("(revised from ...)") are formatted too. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}(?!T)/.test(value)) return value.replace(ISO_DAY, dayLabel);
  return dayLabel(value);
}

/** "Jun 24" */
export function formatDayMonth(value: string | null | undefined): string {
  if (!value) return "";
  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(intlLocale(), { month: "short", day: "numeric" });
}

/** "Fri, Aug 21", or "Fri, Jan 2, 2027" outside the current year. */
export function formatWeekday(value: string | null | undefined): string {
  if (!value) return "";
  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) return value;
  const year = date.getFullYear() === new Date().getFullYear() ? undefined : "numeric";
  return date.toLocaleDateString(intlLocale(), { weekday: "short", month: "short", day: "numeric", year });
}

/** "1 order", "3 orders". */
export function plural(count: number, one: string, many = `${one}s`): string {
  const noun = count === 1 ? one : many;
  return `${formatNumber(count)} ${t(noun)}`;
}

/** "12 days of cover", "1 day of cover", "<1 day of cover". */
export function coverLabel(days: number): string {
  if (currentLocale() === "zh-CN") return days < 1 ? "不足 1 天库存覆盖" : `${formatNumber(Math.round(days))} 天库存覆盖`;
  return days < 1 ? "<1 day of cover" : `${plural(Math.round(days), "day")} of cover`;
}

/** "sells out in ~4 days", "sells out within a day". */
export function runwayLabel(days: number): string {
  if (currentLocale() === "zh-CN") return days < 1 ? "将在一天内售罄" : `约 ${formatNumber(Math.round(days))} 天后售罄`;
  return days < 1 ? "sells out within a day" : `sells out in ~${plural(Math.round(days), "day")}`;
}

/** What can still be chosen on a product with options, and what a variant chose. */
export interface OptionFields {
  price: number;
  currency?: string;
  options?: Record<string, string[]>;
  option_values?: Record<string, string>;
}

/** True for a family record: the cart takes one of its variants, chosen with the assistant. */
export function hasOptions(product: Pick<OptionFields, "options">): boolean {
  return Object.keys(product.options ?? {}).length > 0;
}

/** "twin · full · queen · king", one group per option separated by " / "; empty for a plain product. */
export function optionSummary(product: Pick<OptionFields, "options">): string {
  return Object.values(product.options ?? {})
    .map((values) => values.map((value) => t(value)).join(" · "))
    .join(" / ");
}

/** "king · slate" for a variant or a cart line; empty when nothing was chosen. */
export function optionValuesLabel(item: Pick<OptionFields, "option_values">): string {
  return Object.values(item.option_values ?? {}).map((value) => t(value)).join(" · ");
}

/** "From $349" on a family record, whose price is its lowest variant's; the plain price otherwise. */
export function priceLabel(product: OptionFields): string {
  const money = formatMoney(product.price, product.currency);
  return hasOptions(product) ? `${t("From ")}${money}` : money;
}

export function titleCase(value: string): string {
  const title = value.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
  return t(title) === title ? t(title.toLowerCase()) : t(title);
}

/** "attributes_min_nights" as "Min nights". */
export function humanizeField(field: string): string {
  return titleCase(field.replace(/^attributes?_/, ""));
}

// Diff fields are typed by name; a vertical adds its own names (travel's nightly `rate` is money,
// retail's `return_rate` a percent).
const CURRENCY_FIELD = /(^|_)(price|cost|budget|spend|revenue|amount|fee|total)(_|$)/;
const PERCENT_FIELD = /(^|_)(pct|percent|margin)(_|$)/;
const COUNT_FIELD = /(^|_)(stock|quantity|units|count|seats|nights)(_|$)/;

export interface FieldKinds {
  currency?: string[];
  percent?: string[];
}

/** Renders a staged change's before/after value by what its field name says it is. */
export function formatFieldValue(field: string, value: unknown, kinds: FieldKinds = {}): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return t(value ? "Yes" : "No");
  const isCurrency = kinds.currency?.includes(field) || CURRENCY_FIELD.test(field);
  const isPercent = !isCurrency && (kinds.percent?.includes(field) || PERCENT_FIELD.test(field));
  const isCount = COUNT_FIELD.test(field);
  // Numeric fields sometimes arrive as strings; other strings (ids like "0012") stay verbatim.
  if (typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value.trim()) && (isCurrency || isPercent || isCount)) {
    value = Number(value);
  }
  if (typeof value === "number") {
    if (isCurrency) return formatMoney(value);
    if (isPercent) return formatRate(value);
    return Number.isInteger(value) ? formatNumber(value) : value.toFixed(2);
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const ISO_RANGE = /^(\d{4}-\d{2}-\d{2})\s*\/\s*(\d{4}-\d{2}-\d{2})$/;

/** "2026-06-19/2026-06-25" as "Jun 19–25". */
export function formatPeriodLabel(value: string | null | undefined): string {
  if (!value) return "";
  const match = ISO_RANGE.exec(value.trim());
  if (!match) return value;
  const start = parseDate(match[1]);
  const end = parseDate(match[2]);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return value;
  if (start.getFullYear() !== end.getFullYear()) {
    return `${formatDate(match[1])} – ${formatDate(match[2])}`;
  }
  if (start.getMonth() !== end.getMonth()) {
    return `${formatDayMonth(match[1])} – ${formatDayMonth(match[2])}`;
  }
  return `${formatDayMonth(match[1])}–${end.getDate()}`;
}

/** "prior week"/"prior period" when the windows abut at equal length; else the window's label. */
export function formatComparisonLabel(
  period: string | null | undefined,
  compareTo: string | null | undefined,
): string {
  if (!compareTo) return "";
  const primary = ISO_RANGE.exec(period?.trim() ?? "");
  const compare = ISO_RANGE.exec(compareTo.trim());
  if (primary && compare) {
    const dayMs = 24 * 60 * 60 * 1000;
    const primaryStart = parseDate(primary[1]).getTime();
    const primaryDays = Math.round((parseDate(primary[2]).getTime() - primaryStart) / dayMs);
    const compareEnd = parseDate(compare[2]).getTime();
    const compareDays = Math.round((compareEnd - parseDate(compare[1]).getTime()) / dayMs);
    if (primaryDays === compareDays && Math.round((primaryStart - compareEnd) / dayMs) === 1) {
      return primaryDays === 6 ? t("prior week") : t("prior period");
    }
  }
  return formatPeriodLabel(compareTo);
}

export function describeProposer(change: {
  created_by: string;
  created_by_kind?: "operator" | "agent";
}): string {
  return change.created_by_kind === "agent"
    ? currentLocale() === "zh-CN" ? `由 ${change.created_by} 的助手提议` : `Proposed by ${change.created_by}'s assistant`
    : currentLocale() === "zh-CN" ? `由 ${change.created_by} 暂存` : `Staged by ${change.created_by}`;
}

/** Approvals are always a person. */
export function describeResolver(change: {
  status: string;
  applied_by?: string | null;
  discarded_by?: string | null;
  discarded_by_kind?: "operator" | "agent" | null;
}): string | null {
  if (change.status === "applied" && change.applied_by) return currentLocale() === "zh-CN" ? `由 ${change.applied_by} 批准` : `Approved by ${change.applied_by}`;
  if (change.status === "discarded" && change.discarded_by) {
    return change.discarded_by_kind === "agent"
      ? currentLocale() === "zh-CN" ? `由 ${change.discarded_by} 的助手忽略` : `Dismissed by ${change.discarded_by}'s assistant`
      : currentLocale() === "zh-CN" ? `由 ${change.discarded_by} 忽略` : `Dismissed by ${change.discarded_by}`;
  }
  return null;
}

/** "Good morning" before noon, "Good afternoon" until six, then "Good evening". */
export function greeting(now: Date): string {
  const hour = now.getHours();
  if (hour < 12) return t("Good morning");
  if (hour < 18) return t("Good afternoon");
  return t("Good evening");
}

export interface HandoffLink {
  url: string;
  label?: string;
  seller?: string;
}

/** The checkout handoffs a card may link to: https only (http on localhost for development).
 * The URL comes from the backend, never the model; the scheme check is defense in depth. */
export function safeHandoffs(handoffs: HandoffLink[] | undefined): HandoffLink[] {
  return (handoffs ?? []).filter((h) => {
    try {
      const u = new URL(h.url);
      return u.protocol === "https:" || (u.protocol === "http:" && ["localhost", "127.0.0.1"].includes(u.hostname));
    } catch {
      return false;
    }
  });
}
