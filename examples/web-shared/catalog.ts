// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { useEffect, useState } from "react";
import { useLocale, type Locale } from "./i18n";

type Loader<P> = () => Promise<P[] | null>;

const indexes = new WeakMap<object, Map<Locale, Promise<Record<string, unknown>>>>();

/** Loaded once per page, keyed on `load`; empty until then and when the API is down. */
export function useCatalogIndex<P extends { product_id: string }>(
  load: Loader<P>,
): Record<string, P> {
  const { locale } = useLocale();
  const [index, setIndex] = useState<Record<string, P>>({});
  useEffect(() => {
    const localized = indexes.get(load) ?? new Map<Locale, Promise<Record<string, unknown>>>();
    let promise = localized.get(locale) as Promise<Record<string, P>> | undefined;
    if (!promise) {
      promise = load().then((products) =>
        Object.fromEntries((products ?? []).map((product) => [product.product_id, product])),
      );
      localized.set(locale, promise);
      indexes.set(load, localized);
    }
    let mounted = true;
    void promise.then((value) => {
      if (mounted) setIndex(value);
    });
    return () => {
      mounted = false;
    };
  }, [load, locale]);
  return index;
}
