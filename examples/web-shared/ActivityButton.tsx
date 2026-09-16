// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { currentLocale, t } from "./i18n";

/** Opens the Activity panel; pulses while a reply streams and counts facts saved this session. */
export function ActivityButton({
  streaming,
  newMemoryCount,
  onClick,
}: {
  streaming: boolean;
  newMemoryCount: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={t("Activity")}
      className="flex items-center gap-1.5 rounded-full border border-(--line) bg-(--card) px-3 py-1 text-[13px] font-semibold text-(--ink) transition hover:border-(--accent)"
    >
      {streaming ? (
        <span className="relative flex h-2 w-2" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-(--accent) opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-(--accent)" />
        </span>
      ) : null}
      <span className="hidden sm:inline">{t("Activity")}</span>
      <span className="sm:hidden" aria-hidden>◷</span>
      {newMemoryCount > 0 ? (
        <span
          className="rounded-full bg-(--accent-soft) px-1.5 py-0.5 text-[11px] font-bold text-(--ink)"
          title={currentLocale() === "zh-CN" ? `本次会话已保存 ${newMemoryCount} 条信息` : `${newMemoryCount} fact${newMemoryCount === 1 ? "" : "s"} saved this session`}
        >
          {newMemoryCount}
        </span>
      ) : null}
    </button>
  );
}
