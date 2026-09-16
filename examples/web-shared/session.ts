// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { useCallback, useEffect, useState } from "react";
import type { AgentApi } from "./api";

export interface Session {
  /** Null while login is in flight or after it failed. */
  sessionId: string | null;
  /** The signed-in operator's name, on merchant sessions. */
  operator?: string;
  /** The signed-in shopper, on storefront sessions. */
  shopper?: { name: string; tier?: string };
}

const generations = new WeakMap<AgentApi, number>();

/**
 * Only the newest start installs its token. Key the caller on the profile so per-session
 * state resets with it.
 */
export function useSession(
  api: AgentApi,
  options: { profile?: string } = {},
): Session & { status: "connecting" | "ready" | "failed"; retry: () => void } {
  const { profile } = options;
  const [session, setSession] = useState<Session>({ sessionId: null });
  const [status, setStatus] = useState<"connecting" | "ready" | "failed">("connecting");
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => {
    setStatus("connecting");
    setAttempt((value) => value + 1);
  }, []);

  useEffect(() => {
    const generation = (generations.get(api) ?? 0) + 1;
    generations.set(api, generation);
    const current = () => generations.get(api) === generation;
    api.session = null;
    setSession({ sessionId: null });
    setStatus("connecting");
    void (async () => {
      const started = await api.startSession(profile ? { user_id: profile } : undefined);
      if (!current()) return;
      api.session = started?.sessionId ?? null;
      setSession({ sessionId: started?.sessionId ?? null, operator: started?.operator, shopper: started?.shopper });
      setStatus(started ? "ready" : "failed");
    })();
    return () => {
      generations.set(api, (generations.get(api) ?? 0) + 1);
    };
  }, [api, profile, attempt]);

  return { ...session, status, retry };
}
