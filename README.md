<div align="center">

# RiMo

### An autonomous AI software engineering company

**Ten specialist agents that plan, build, review, test, secure, and ship software around the clock.**

[Architecture](docs/architecture.md) · [Database Schema](docs/database-schema.md) · [Deployment](docs/deployment.md)

</div>

---

RiMo (Rishik Mora AI) accepts a project idea or a GitHub repository and operates on it like a real engineering org: a CEO agent sets the mission, a Planner breaks it into a dependency-ordered backlog, an Architect designs, a Builder writes the code, and Reviewer / QA / Security form a quality gate before anything is committed, PR'd, merged, or deployed — with a human in the loop at the high-risk boundaries. A Memory agent distills every run into durable, reusable knowledge.

This is a working system, not a mock: a resumable orchestration engine, a real Anthropic tool-calling loop, pgvector-backed long-term memory, GitHub integration, secret scanning, human-approval gates, and a live operations dashboard.

## The company

| Agent | Mandate |
|-------|---------|
| **CEO** | Mission planning, objectives, long-term strategy |
| **Research** | Documentation, prior art, competitor analysis |
| **Planner** | Roadmap → scoped, prioritized, dependency-aware tasks |
| **Architect** | System design and Architecture Decision Records |
| **Builder** | Writes and refactors production code |
| **Reviewer** | Code review with a 0–100 quality score |
| **QA** | Unit, integration, and E2E testing |
| **Security** | Vulnerability scans and secret detection |
| **DevOps** | Deployment, monitoring, rollbacks |
| **Memory** | Learns from every run; powers semantic recall |

## How it works

```
plan (CEO → Planner)
  └▶ per task, in priority order:
        architect → build → [review + qa + security] → commit → PR → merge* → deploy*
  └▶ learn (Memory)
                                              * gated by human approval
```

State lives in Postgres, tasks carry time-bound leases, and a single `tick()` advances one unit of work — so the worker can run 24/7 and self-heal from crashes. Full detail in [the architecture doc](docs/architecture.md).

## Tech stack

**Backend** — FastAPI · async SQLAlchemy 2.0 · PostgreSQL + pgvector · Redis · Anthropic Claude (Opus 4.8 + Haiku) · Alembic
**Frontend** — Next.js 16 · TypeScript · TailwindCSS · Server-Sent Events
**Infra** — Docker · Kubernetes · GitHub Actions CI/CD

## Quick start

```bash
cp .env.example .env          # set SECRET_KEY and ANTHROPIC_API_KEY
docker compose up --build
```

Then open the dashboard at **http://localhost:3000**, create a project, and click **Start company**. API docs are at **http://localhost:8000/docs**.

Other ways to run it (local dev with hot reload, full Kubernetes) are in the [deployment guide](docs/deployment.md).

## Repository layout

```
rimo/
├── backend/                 FastAPI app, agents, orchestrator, memory
│   ├── app/
│   │   ├── agents/          the ten specialists + registry + tools
│   │   ├── orchestration/   the autonomous loop, worker, event bus
│   │   ├── memory/          pgvector semantic memory
│   │   ├── integrations/    GitHub App client
│   │   ├── services/        LLM loop, embeddings, safety
│   │   ├── api/             auth, projects, resources, SSE events
│   │   └── models/          SQLAlchemy schema + enums
│   ├── migrations/          Alembic
│   └── tests/               pytest suite
├── frontend/                Next.js operations dashboard
│   └── src/
│       ├── app/             routes (operations, projects, floor, login)
│       ├── components/      agent floor, activity timeline, UI
│       └── lib/             typed API client
├── infra/k8s/               Kubernetes manifests
├── .github/workflows/       CI/CD pipeline
└── docs/                    architecture · schema · deployment
```

## Safety

RiMo is built to be trusted with real repositories:

- **Human-in-the-loop** approval gates for merge, deploy, and any destructive action (on by default).
- **Secret scanning** (pattern + entropy) on every staged change, with redaction.
- **Repository deletion disabled** platform-wide unless explicitly enabled — and even then it always requires approval.
- **A hard cap** on files changed per PR.
- Secrets are read from the environment / a vault and never committed.

## Development

```bash
# backend
cd backend && pip install -r requirements.txt
ruff check app && pytest

# frontend
cd frontend && npm install
npm run typecheck && npm run lint && npm run build
```

CI runs all of the above on every push, builds both Docker images, and pushes them to GHCR on `main`.

---

<div align="center">
<sub>Built by Rishik Mora.</sub>
</div>
