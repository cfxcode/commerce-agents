// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import { ZH_CN } from "./locales/zh-CN";
const DATA_ZH_CN: Record<string, string> = {};

export function registerTranslations(translations: Record<string, string>): void {
  Object.assign(DATA_ZH_CN, translations);
}

export type Locale = "en" | "zh-CN";

let activeLocale: Locale = "en";

export function normalizedLocale(value: string | null | undefined): Locale {
  return value?.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}

export function setCurrentLocale(locale: Locale): void {
  activeLocale = locale;
}

export function currentLocale(): Locale {
  return activeLocale;
}

export function translate(text: string, locale: Locale = activeLocale): string {
  if (locale === "en" || !text) return text;
  const direct = ZH_CN[text] ?? DATA_ZH_CN[text];
  if (direct) return direct;
  const trimmed = text.trim();
  const localized = ZH_CN[trimmed] ?? DATA_ZH_CN[trimmed] ?? translatePattern(trimmed);
  return localized ? text.replace(trimmed, localized) : text;
}

function translatePattern(text: string): string | undefined {
  let match = /^(\d{4}-\d{2}-\d{2}) \(updated after a (carrier|warehouse) delay; the original (\d{4}-\d{2}-\d{2}) estimate was missed\)$/.exec(text);
  if (match) return `${match[1]} (因${match[2] === "carrier" ? "承运商" : "仓库"}延迟而更新；原预计 ${match[3]} 未能按时送达)`;
  match = /^Get it by \w+, (\w+) (\d+)$/.exec(text);
  if (match) {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const month = months.indexOf(match[1]) + 1;
    return month ? `${month}月${match[2]}日前送达` : undefined;
  }
  match = /^today by (\d+) (AM|PM)$/.exec(text);
  if (match) return `今天${match[2] === "AM" ? "上午" : "下午"}${match[1]}点前`;
  match = /^Returns on (.+) are running at ([\d.]+)%$/.exec(text);
  if (match) return `${translate(match[1], "zh-CN")} 的退货率为 ${match[2]}%`;
  match = /^([\d.]+)% of units come back(?: on (\d+) sales in 30 days)?; worth a look at the listing content before restocking\.$/.exec(text);
  if (match) return `${match[1]}% 的商品被退回${match[2] ? `，近 30 天售出 ${match[2]} 件` : ""}；补货前值得检查商品内容。`;
  match = /^Returns on (.+) \(([^)]+)\) are at ([\d.]+)%\. What's the likely cause and what would you change\?$/.exec(text);
  if (match) return `${translate(match[1], "zh-CN")}（${match[2]}）的退货率为 ${match[3]}%。可能的原因是什么，你建议如何调整？`;
  match = /^Kids' room sales are (up|down) ([\d.]+)% week-over-week$/.exec(text);
  if (match) return `儿童房商品销售额环比${match[1] === "up" ? "上升" : "下降"} ${match[2]}%`;
  match = /^Kids' room sales are (up|down) ([\d.]+)% week-over-week\. What's driving it, and is anything at risk of stocking out\?$/.exec(text);
  if (match) return `儿童房商品销售额环比${match[1] === "up" ? "上升" : "下降"} ${match[2]}%。驱动因素是什么，是否有商品即将缺货？`;
  match = /^(\$[\d,]+) this week vs (\$[\d,]+) last week for the kids-room segment\.$/.exec(text);
  if (match) return `儿童房商品本周销售额 ${match[1]}，上周 ${match[2]}。`;
  match = /^(.+) returns (\$[\d.]+) per \$1 spent; (.+) returns (\$[\d.]+)\.$/.exec(text);
  if (match) return `${translate(match[1], "zh-CN")} 每投入 1 美元带来 ${match[2]} 收入；${translate(match[3], "zh-CN")} 带来 ${match[4]}。`;
  match = /^(.+) is returning (\$[\d.]+) per \$1 vs (\$[\d.]+) for (.+)\. Should budget move between them\?$/.exec(text);
  if (match) return `${translate(match[1], "zh-CN")} 每投入 1 美元带来 ${match[2]} 收入，${translate(match[4], "zh-CN")} 为 ${match[3]}。是否应该调整两者预算？`;
  match = /^(\$[\d.]+) is (near this item's 90-day low|this item's typical price|above this item's typical price) \(90-day range (\$[\d.]+)–(\$[\d.]+)\)$/.exec(text);
  if (match) return `${match[1]} ${match[2].startsWith("near") ? "接近该商品 90 天最低价" : match[2].startsWith("above") ? "高于该商品常见价格" : "是该商品的常见价格"}（90 天区间 ${match[3]}–${match[4]}）`;
  match = /^(.+) (trend|over the period)$/.exec(text);
  if (match) return `${translate(match[1], "zh-CN")}走势`;
  return undefined;
}

export const t = translate;

const CANONICAL_FIELDS = new Set([
  "type", "component", "status", "kind", "category", "labels", "tool", "field", "target",
  "product_id", "listing_id", "order_id", "policy_id", "session_id", "merchant_id", "user_id",
  "change_id", "campaign_id", "insight_id", "variant_of", "options", "option_values", "currency",
  "url", "image_url", "tracking_url", "query", "created_by", "applied_by", "discarded_by", "tier",
]);

export function translateDeep<T>(value: T, locale: Locale = activeLocale): T {
  if (locale === "en") return value;
  if (typeof value === "string") return translate(value, locale) as T;
  if (Array.isArray(value)) return value.map((item) => translateDeep(item, locale)) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, CANONICAL_FIELDS.has(key) ? item : translateDeep(item, locale)]),
    ) as T;
  }
  return value;
}
