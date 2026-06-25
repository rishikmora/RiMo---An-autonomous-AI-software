"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, getToken, streamUrl } from "@/lib/api";
import type { ActivityEvent } from "@/types";

/** Poll an async fetcher on an interval, with manual refetch and error state. */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs = 5000,
  deps: unknown[] = [],
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  // `loading` is reset to true the moment `deps` changes, computed during
  // render by comparing against the deps that produced the current data —
  // the React-documented way to "adjust state when a prop changes" without a
  // synchronous setState-in-effect. lastDeps lives in state (not a ref) so
  // it's safe to read during render.
  const [loading, setLoading] = useState(true);
  const [lastDeps, setLastDeps] = useState(deps);
  const depsChanged = deps.length !== lastDeps.length || deps.some((d, i) => d !== lastDeps[i]);
  if (depsChanged) {
    setLastDeps(deps);
    setLoading(true);
  }

  const savedFetcher = useRef(fetcher);
  useEffect(() => {
    savedFetcher.current = fetcher;
  }, [fetcher]);

  const refetch = useCallback(async () => {
    try {
      const result = await savedFetcher.current();
      setData(result);
      setError(null);
    } catch (e) {
      setError(e as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void refetch();
    const id = setInterval(() => {
      if (active && document.visibilityState === "visible") void refetch();
    }, intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, refetch };
}

/** Subscribe to the project's live activity stream over SSE, with a seed list. */
export function useActivityStream(projectId: string, seed: ActivityEvent[] = []) {
  const [events, setEvents] = useState<ActivityEvent[]>(seed);
  const [connected, setConnected] = useState(false);
  // Re-seed when the seed actually changes for this project. Tracking the
  // previous key in state (not a ref) is what makes this safe to read and
  // update during render.
  const [seedKey, setSeedKey] = useState(`${projectId}:${seed.length}`);
  const nextSeedKey = `${projectId}:${seed.length}`;
  if (nextSeedKey !== seedKey) {
    setSeedKey(nextSeedKey);
    setEvents(seed);
  }

  useEffect(() => {
    if (!projectId || !getToken()) return;
    const es = new EventSource(streamUrl(projectId));
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    const ingest = (msg: MessageEvent) => {
      try {
        const evt = JSON.parse(msg.data) as ActivityEvent;
        setEvents((prev) => [evt, ...prev].slice(0, 200));
      } catch {
        /* ignore malformed frames */
      }
    };

    // The backend emits named SSE events (event: agent_started, etc.), which do
    // not trigger the default onmessage handler. Subscribe to each known type
    // plus the generic "message" fallback.
    const types = [
      "message",
      "agent_started",
      "agent_step",
      "agent_succeeded",
      "agent_failed",
      "task_created",
      "pr_opened",
      "pr_merged",
      "deploy_started",
      "deploy_succeeded",
      "approval_requested",
      "project_status",
    ];
    types.forEach((t) => es.addEventListener(t, ingest as EventListener));

    return () => {
      types.forEach((t) => es.removeEventListener(t, ingest as EventListener));
      es.close();
    };
  }, [projectId]);

  return { events, connected };
}

/** Resolve the signed-in user once; redirect to /login on failure. */
export function useAuth() {
  const [user, setUser] = useState<{ email: string; full_name: string | null } | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api
      .me()
      .then((u) => setUser(u))
      .catch(() => {
        window.location.href = "/login";
      })
      .finally(() => setReady(true));
  }, []);

  return { user, ready };
}
