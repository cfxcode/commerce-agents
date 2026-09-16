// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { useId } from "react";
import { currentLocale, formatMoney, useCatalogIndex, safeHandoffs, t } from "web-shared";
import { fetchProducts } from "@/lib/api";
import type { CheckoutPayload, Product } from "@/lib/types";
import { STORE_POLICY } from "@/lib/storePolicy";
import { DeliveryPromise, ProductImage } from "../ProductTile";

export default function CheckoutSummary({ payload }: { payload: CheckoutPayload }) {
  const cart = payload.cart;
  const handoffs = safeHandoffs(payload.handoffs);
  // Several summaries can coexist across turns, so the describedby id is per card.
  const handoffNoteId = useId();
  // Summary lines carry only title, price, and quantity; the catalog supplies delivery
  // dates and thumbnails.
  const catalog = useCatalogIndex(fetchProducts);
  // The policy says "over" the threshold, so a cart at exactly the threshold is not free.
  const freeShipping = cart.subtotal > STORE_POLICY.freeShippingThreshold;
  return (
    <section data-checkout-card className="rounded-2xl border-2 border-(--accent) bg-(--card) p-4 shadow-(--shadow-sm)">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[15px] font-semibold text-(--ink)">{t("Ready to check out")}</h3>
        <div className="flex items-center gap-1.5">
          <span className="whitespace-nowrap rounded-full border border-(--line) bg-(--well)/60 px-2.5 py-0.5 text-[11px] font-semibold text-(--ink-soft)">
            {currentLocale() === "zh-CN" ? "尚未扣款" : "Not charged"}
          </span>
          {payload.fulfillment_method ? (
            <span className="rounded-full bg-(--accent-soft) px-2.5 py-0.5 text-[13px] font-semibold capitalize text-(--ink)">
              {payload.fulfillment_method}
            </span>
          ) : null}
        </div>
      </div>
      {payload.note ? <p className="mt-1 text-[13px] text-(--ink-soft)">{payload.note}</p> : null}
      <div className="mt-3 space-y-2 rounded-lg bg-(--well)/60 p-3 text-sm">
        {cart.items.map((item) => {
          const product: Product =
            catalog[item.product_id] ?? {
              product_id: item.product_id,
              title: item.title,
              price: item.price,
            };
          return (
            <div key={item.product_id} className="flex items-center gap-2.5">
              <ProductImage
                product={product}
                className="h-10 w-10 shrink-0 rounded-lg !text-xl"
              />
              <div className="min-w-0 flex-1">
                <div className="flex justify-between gap-2">
                  <span className="line-clamp-1 text-(--ink)" title={item.title}>
                    {item.title} × {item.quantity}
                  </span>
                  <span className="shrink-0 text-(--ink)">{formatMoney(item.line_total)}</span>
                </div>
                <DeliveryPromise product={product} />
              </div>
            </div>
          );
        })}
        <div className="flex justify-between border-t border-(--line) pt-1.5 text-(--ink)">
          <span>{t("Subtotal")}</span>
          <span>{formatMoney(cart.subtotal, cart.currency)}</span>
        </div>
        <div className="flex justify-between gap-2 text-(--ink)">
          <span>
            {currentLocale() === "zh-CN" ? "配送 " : "Shipping "}
            <span className="text-[13px] text-(--ink-soft)">
              {currentLocale() === "zh-CN" ? `标准配送 · ${t(STORE_POLICY.standardShippingEta)}` : `standard · ${STORE_POLICY.standardShippingEta}`}
            </span>
          </span>
          <span className={freeShipping ? "font-medium text-(--ok)" : "text-(--ink)"}>
            {freeShipping ? (currentLocale() === "zh-CN" ? "免费" : "Free") : t("Calculated at checkout")}
          </span>
        </div>
        {!freeShipping && STORE_POLICY.freeShippingThreshold - cart.subtotal > 0 ? (
          <div className="flex justify-between text-[13px] text-(--ink-soft)">
            <span>
              {currentLocale() === "zh-CN" ? `再添加 ${formatMoney(STORE_POLICY.freeShippingThreshold - cart.subtotal)} 即可免运费` : `Add ${formatMoney(STORE_POLICY.freeShippingThreshold - cart.subtotal)} more to unlock free shipping`}
            </span>
          </div>
        ) : null}
        <div className="flex justify-between text-(--ink)">
          <span>{t("Tax")}</span>
          <span>{t("Calculated at checkout")}</span>
        </div>
        <div className="flex justify-between border-t border-(--line) pt-1.5 text-base font-bold text-(--ink)">
          <span>{t("Estimated total")}</span>
          <span>{formatMoney(cart.subtotal, cart.currency)}</span>
        </div>
        <p className="text-[11px] leading-snug text-(--ink-soft)">
          {currentLocale() === "zh-CN" ? (freeShipping ? "税前金额；最终金额将在结账时显示。" : "运费及税费前金额；最终金额将在结账时显示。") : `${freeShipping ? "Before tax" : "Before shipping and tax"}; the final total appears at checkout.`}
        </p>
      </div>
      <p className="mt-2 text-[11px] text-(--ink-soft)">{t(STORE_POLICY.returnsLine)}</p>
      {handoffs.length ? (
        // The backend named where payment happens (a hosted checkout URL, or one per seller).
        <div className="mt-3 flex flex-col gap-2">
          {handoffs.map((h) => (
            <a
              key={h.url}
              href={h.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-describedby={handoffNoteId}
              className="w-full rounded-xl bg-(--accent) py-2.5 text-center text-sm font-bold text-(--ink)"
            >
              {h.label ?? (currentLocale() === "zh-CN" ? (h.seller ? `前往 ${h.seller} 结账` : "继续结账") : (h.seller ? `Continue to checkout with ${h.seller}` : "Continue to checkout"))}
            </a>
          ))}
        </div>
      ) : (
        // Disabled so assistive tech is not offered a focusable no-op.
        <button
          disabled
          aria-disabled
          aria-describedby={handoffNoteId}
          className="mt-3 w-full cursor-not-allowed rounded-xl bg-(--accent) py-2.5 text-sm font-bold text-(--ink) opacity-90"
          title={t("Nothing is charged here. Payment happens when you check out.")}
        >
          {currentLocale() === "zh-CN" ? "继续结账" : "Continue to checkout"}
        </button>
      )}
      <p id={handoffNoteId} className="mt-2 text-center text-[11px] text-(--ink-soft)/80">
        {t("Nothing is charged here. Payment happens when you check out.")}
      </p>
    </section>
  );
}
