// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { normalizedLocale, registerTranslations, setCurrentLocale, type Locale } from "./i18n-core";
export { currentLocale, t, translate, translateDeep, type Locale } from "./i18n-core";

const STORAGE_KEY = "acme-locale";

interface LocaleState {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

const LocaleContext = createContext<LocaleState>({
  locale: "en",
  setLocale: () => undefined,
});

export function LocaleProvider({ children, translations }: { children: ReactNode; translations?: Record<string, string> }) {
  const [locale, setLocaleState] = useState<Locale>("en");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (translations) registerTranslations(translations);
    const cookie = document.cookie.split("; ").find((item) => item.startsWith(`${STORAGE_KEY}=`))?.split("=")[1];
    let saved: string | null = cookie ?? null;
    try { saved ??= window.localStorage.getItem(STORAGE_KEY); } catch { /* Storage may be disabled. */ }
    const initial = normalizedLocale(saved ?? window.navigator.language);
    setCurrentLocale(initial);
    setLocaleState(initial);
    document.documentElement.lang = initial;
    setReady(true);
  }, [translations]);

  const setLocale = (next: Locale) => {
    setCurrentLocale(next);
    try { window.localStorage.setItem(STORAGE_KEY, next); } catch { /* The cookie remains usable. */ }
    document.cookie = `${STORAGE_KEY}=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
    document.documentElement.lang = next;
    setLocaleState(next);
  };

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      {ready ? children : <div className="h-dvh animate-pulse bg-(--ground)" aria-busy="true" />}
    </LocaleContext.Provider>
  );
}

export function useLocale(): LocaleState {
  return useContext(LocaleContext);
}

export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const { locale, setLocale } = useLocale();
  return (
    <div className={`inline-flex rounded-lg border border-black/10 bg-white/90 p-0.5 text-xs font-semibold shadow-sm backdrop-blur ${className}`} role="group" aria-label={locale === "zh-CN" ? "语言" : "Language"}>
      <button type="button" onClick={() => setLocale("zh-CN")} className={`rounded-md px-1.5 py-1.5 sm:px-2.5 ${locale === "zh-CN" ? "bg-black text-white" : "text-black/60 hover:text-black"}`} aria-pressed={locale === "zh-CN"}>中文</button>
      <button type="button" onClick={() => setLocale("en")} className={`rounded-md px-1.5 py-1.5 sm:px-2.5 ${locale === "en" ? "bg-black text-white" : "text-black/60 hover:text-black"}`} aria-pressed={locale === "en"}>EN</button>
    </div>
  );
}
