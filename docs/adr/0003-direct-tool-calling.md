# ADR 0003 — Direct Anthropic tool-calling instead of an agent framework

**Status:** Accepted
**Date:** 2026-01

## Context

RiMo orchestrates ten specialist agents, each running a tool-using reasoning
loop. Frameworks exist for exactly this (LangGraph, CrewAI, AutoGen), and using
one would be the path of least initial resistance.

## Decision

Build the agent loop **directly on the Anthropic Messages API** — a single
canonical `AgentLoop` (`app/services/llm.py`) that drives the model until it
returns a final answer, dispatching tool calls to a typed `ToolRegistry` — and
implement orchestration ourselves.

## Rationale

- **The orchestration *is* the product.** RiMo's value is the specific
  state machine: lease-based ticks, the review→QA→security quality gate, the
  approval gates, the cost cap, multi-model routing. A framework would want to
  own that control flow; we'd spend our time fighting its abstractions instead of
  expressing ours.
- **Transparency and debuggability.** When an agent run goes wrong, we can read
  one ~200-line loop and a transcript, not trace through a framework's scheduler.
  Trace IDs thread cleanly because we own every call site.
- **Fewer, more stable dependencies.** Agent frameworks move fast and break APIs.
  The Anthropic SDK is a single, stable dependency. Less version churn, smaller
  attack surface, easier to audit.
- **Routing and cost control.** Per-call model selection and the economic ledger
  are woven into our own `_run_agent`; doing that *through* a framework's
  abstraction would be awkward and partial.

## Consequences

- We implement (and test) our own tool loop, retry/backoff, and transcript
  capture rather than getting them off the shelf. This is ~a few hundred lines,
  and it's covered by tests.
- We don't get a framework's prebuilt integrations; for RiMo's tool set
  (workspace files, GitHub, web search, memory) we wanted thin custom tools anyway.
- Multi-provider support (OpenAI/Google for routing) is something we add
  deliberately at the `LLMClient` boundary rather than inheriting.

## Alternatives considered

- **LangGraph.** Good graph-based control flow, but it wants to own the state
  machine that is precisely the thing we need full control over.
- **CrewAI / AutoGen.** Fast to prototype "a crew of agents," but opinionated
  abstractions that obscure the exact gating and cost-control behavior RiMo
  depends on, and a heavier dependency to keep current.
