# RiMo — Intelligence Layer

Beyond the core ten-agent pipeline, RiMo ships an advanced capability layer that
most agent systems lack. These subsystems make the company *understand* its
codebase, *learn* from its history, *reason* about cost, *recover* from failure,
and *improve itself* over time. Each is a real, tested module wired into the
running system — not a stub.

---

## 1. Knowledge Graph — the structural brain

`app/orchestration/graph.py`

RiMo builds a typed graph of the codebase: modules, files, classes, functions,
API routes, database tables, and external dependencies, plus the relationships
between them (imports, calls, defines, inherits, depends-on). Extraction is
language-aware — Python via the `ast` module (precise), JS/TS/TSX via robust
regexes.

After ingestion, a **PageRank** pass scores each node's centrality, so the most
load-bearing parts of the system rank highest. Agents query the graph to
understand blast radius before they change anything.

- Rebuilt automatically during the worker's maintenance cycle from the connected repo.
- Exposed at `GET /projects/{id}/graph` and `/graph/central`.
- Verified on RiMo's own backend: 427 nodes, 2,095 edges, all routes and tables mapped.

## 2. Long-term memory

`app/memory/service.py` (core) + the `model_calls`, `incidents`, and
`prompt_executions` ledgers.

Every bug, PR, architecture decision, failed attempt, and successful
implementation is retained: the pgvector memory store holds distilled lessons
(semantic recall), while the new ledgers retain the full operational history —
what was tried, what it cost, and what happened. Future agents recall this
before acting.

## 3. Agent Debate System

`app/orchestration/debate.py`

Single-agent output is a first draft. RiMo runs a bounded, structured debate —
Architect → Reviewer → Security → QA — where each specialist must endorse or
challenge the prior positions with specific, actionable critique. The engine
consolidates a consensus verdict and a deduplicated set of required changes,
which feed back to the Builder before the quality gate. Blocking objections stop
a merge cold.

## 4. Autonomous Research Engine

`app/orchestration/research.py`

RiMo surveys the outside world — releases, libraries, papers, trends,
competitors — relevant to a project's stack and mission, then distills findings
into concrete, scoped task proposals. Proposals enter the backlog for the
Planner to prioritize; nothing ships without human/CEO direction. Triggered via
`POST /projects/{id}/research` and run on the maintenance cycle.

## 5. Multi-Model Routing

`app/services/router.py` — **wired into every agent run**

RiMo never hard-codes one model. Each unit of work is classified into a
complexity tier (trivial → complex) and routed to the most cost-effective model
that can do it: trivial fixes to a small fast model, system design to a frontier
model. Routing degrades gracefully — if a provider isn't keyed, the best
available Anthropic model is substituted, so the system never blocks.

Typical effect: **70–90% cost reduction** versus "everything on the frontier
model." Realized savings are computed live and shown on the Economics tab.

## 6. Self-Evolving Prompts

`app/services/prompts.py`

Each role can hold multiple prompt variants. RiMo measures each variant's real
success rate and reward in production and selects among them with **Thompson
sampling** — balancing exploitation and exploration with no hand-tuned epsilon.
The weekly self-improvement loop breeds an improved variant from the champion
and retires consistent laggards. Leaderboard at `GET /prompts/{role}`.

## 7. Failure Recovery

`app/services/recovery.py`

When a build, test, or deploy fails, RiMo opens an **incident** and runs a
bounded recovery strategy: diagnose → retry (with a fix) → roll back → escalate.
Every step is recorded on the incident timeline, producing an audit trail and a
post-mortem the Memory agent learns from. Surfaced on the Incidents tab and at
`GET /projects/{id}/incidents`.

## 8. Autonomous Architecture Refactoring

`app/orchestration/refactor.py`

RiMo mines the knowledge graph for objective smells — God objects (excessive
fan-in/out), hub files, circular dependencies, deep dependency chains — and
turns the worst into scoped refactor tasks with migration plans. Every proposal
cites the metric that triggered it, so the backlog stays explainable. Refactors
run behind the normal review **and** benchmark gates (no behavior change, no
regression). At `GET /projects/{id}/smells`.

## 9. Startup Creation Mode

`app/orchestration/product.py` → `StartupFactory`

One line in ("Build an AI CRM") produces a complete initial plan: mission,
architecture outline, an MVP roadmap of scoped tasks, plus standard scaffold
deliverables (landing page, docs, analytics, CI/CD) — all queued without further
prompting by chaining CEO → Architect → Planner.

## 10. Autonomous Product Manager

`app/orchestration/product.py` → `ProductManager`

After launch, the PM ingests product signals — feature usage, crashes, feedback,
retention — and re-prioritizes the backlog the way a human PM would. Crashes
become critical bugfixes; heavily-used features get their related work bumped;
qualitative feedback refines ordering via the model.

## 11. Economic Reasoning

`app/services/economics.py`

Every routed model call is logged to a cost ledger. The economics service
aggregates it into spend by project/agent/model, unit economics (cost per merged
PR, cost per completed task), routing savings vs. a frontier-only baseline, and
a budget guard that turns an overrun into an approval rather than a silent spend.
At `GET /projects/{id}/economics` and `/spend`.

## 12. Autonomous Benchmarking

`app/orchestration/benchmark.py`

Before a change merges, RiMo compares candidate vs. baseline on the metrics that
matter — latency, memory, bundle size, test runtime — and rejects regressions
beyond per-metric tolerances. Benchmarks are pluggable async probes; the harness
returns a pass/fail verdict with a human-readable diff.

## 13. RiMo OS — Fleet Management

`app/orchestration/fleet.py` → `FleetManager`

RiMo runs as an operating system over a portfolio. The fleet scheduler ranks
every project by an **attention score** (pending approvals and blockers dominate)
and decides which projects the worker advances next under a global concurrency
budget. The Fleet page is the portfolio command center. At `GET /fleet`.

## 14. Agent Marketplace

`app/orchestration/fleet.py` → `AgentMarketplace`

Beyond the core ten, a project can dynamically "hire" specialists — Flutter, ML,
Next.js, Data, React Native — registered as `AgentSpec`s. Specialists are matched
to a project automatically from its detected stack. At `GET /marketplace` and
`/projects/{id}/marketplace/recommended`.

## 15. Self-Improvement Loop

`app/orchestration/improvement.py`

On a weekly cadence, RiMo reflects and improves: it mines recent incidents and
failed tasks for recurring causes (stored as memory), evolves prompts for roles
with enough evidence, and surfaces routing-tuning observations — then writes a
self-improvement report the whole company learns from. This is the loop that
makes RiMo compounding rather than static.

---

## How it's wired

The subsystems are not isolated. The **orchestrator** routes every agent call
through the model router and records its cost; its **maintenance cycle** (run by
the worker on a slow cadence) rebuilds the knowledge graph, scans for refactors,
and runs requested research. The **API** exposes all of it under `/api/v1`, and
the **dashboard** surfaces the knowledge graph, economics, and incidents per
project plus the fleet view across projects.

```
worker tick      ──▶ orchestrator.tick()      ──▶ routed agents → cost ledger
worker maintain  ──▶ orchestrator.run_maintenance()
                       ├─ knowledge_graph.rebuild()
                       ├─ refactor_analyzer.propose_refactors()
                       └─ research engine (on request)
weekly           ──▶ self_improvement.run()   ──▶ prompt evolution + lessons
```
