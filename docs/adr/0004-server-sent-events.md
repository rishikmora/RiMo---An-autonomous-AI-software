# ADR 0004 — Server-Sent Events for the live activity stream

**Status:** Accepted
**Date:** 2026-01

## Context

The dashboard shows a live activity timeline — agents starting, steps, PRs
opened, approvals requested — streamed from the backend as work happens. The two
standard choices are WebSockets and Server-Sent Events (SSE).

## Decision

Use **Server-Sent Events**: the orchestrator emits events → persisted to
`activity_events` → fanned out via a Redis-backed event bus → delivered to each
connected `EventSource` on the frontend.

## Rationale

- **The stream is one-directional.** The dashboard *consumes* events; it doesn't
  push data back over the same channel (actions like approve/merge go through
  normal authenticated POSTs). SSE is purpose-built for server→client streaming;
  WebSockets' bidirectionality would be unused complexity.
- **Reconnection is free.** `EventSource` reconnects automatically with built-in
  backoff. With WebSockets we'd implement reconnect/heartbeat logic ourselves.
- **It's just HTTP.** SSE rides over normal HTTP/2, works through standard
  proxies and load balancers with minimal config (we set read timeout and
  disable buffering in the ingress), and needs no protocol upgrade handling.
- **Durable backlog.** Because events are persisted first, a client can fetch the
  recent timeline via a normal REST call and then subscribe — no lost events on
  connect.

## Consequences

- Truly interactive, low-latency client→server messaging (not needed here) would
  require adding WebSockets later. The event model wouldn't change; only the
  transport for that specific feature.
- SSE has a per-browser connection cap per origin; not a concern for a dashboard
  with one stream per open project view.

## Alternatives considered

- **WebSockets.** The right call if we needed bidirectional or binary streaming.
  We don't, and it would add reconnection logic and proxy/upgrade handling for no
  benefit.
- **Polling.** Simplest, but either laggy or wasteful; we already persist events,
  so SSE gives real-time delivery without the polling tax. (We still poll on a
  slow interval as a fallback when SSE can't connect.)

---

## ADR index

- [0001 — Lease-based orchestration](./0001-lease-based-orchestration.md)
- [0002 — Postgres + pgvector](./0002-postgres-pgvector.md)
- [0003 — Direct Anthropic tool-calling](./0003-direct-tool-calling.md)
- [0004 — Server-Sent Events](./0004-server-sent-events.md)
