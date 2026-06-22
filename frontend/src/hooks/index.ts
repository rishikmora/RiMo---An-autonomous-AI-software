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
  const [loading, setLoading] = useState(true);
  const savedFetcher = useRef(fetcher);
  savedFetcher.current = fetcher;

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
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

  useEffect(() => {
    setEvents(seed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed.length, projectId]);

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
