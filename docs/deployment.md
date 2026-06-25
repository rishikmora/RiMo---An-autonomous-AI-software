# RiMo — Deployment Guide

Three ways to run RiMo, from fastest to production: **Docker Compose** (single host), **local dev** (hot reload), and **Kubernetes** (production). All three need the same handful of secrets.

---

## Prerequisites

| For | You need |
|-----|----------|
| Any | An **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com)) — powers all ten agents |
| Real repo operations | A **GitHub App** installed on your repos (App ID, private key, webhook secret) |
| Richer memory (optional) | An **OpenAI API key** for embeddings (falls back to a local embedder if absent) |
| Compose | Docker 24+ and Docker Compose v2 |
| Kubernetes | A cluster, `kubectl`, an ingress controller, a registry |

Generate the JWT signing secret once:

```bash
openssl rand -hex 32
```

---

## Option A — Docker Compose (recommended first run)

```bash
git clone https://github.com/rishikmora/rimo.git
cd rimo
cp .env.example .env
# edit .env: set SECRET_KEY and ANTHROPIC_API_KEY (GitHub creds optional)

docker compose up --build
```

Compose brings up Postgres (with pgvector), Redis, runs the migration job once, then starts the API, the autonomous worker, and the dashboard:

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

Register an account in the dashboard, create a project, and click **Start company**. Tail the worker to watch the agents:

```bash
docker compose logs -f worker
```

Stop and reset:

```bash
docker compose down            # stop
docker compose down -v         # stop + wipe data volumes
```

---

## Option B — Local development

Two terminals, hot reload on both.

**Backend.** Needs a Postgres with pgvector reachable (the Compose `postgres` service works — `docker compose up postgres redis -d`).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export SECRET_KEY=$(openssl rand -hex 32)
export ANTHROPIC_API_KEY=sk-ant-...
export DATABASE_URL='postgresql+asyncpg://rimo:rimo@localhost:5432/rimo'
export REDIS_URL='redis://localhost:6379/0'

# one-time: enable pgvector + migrate
python -c "import psycopg; c=psycopg.connect('postgresql://rimo:rimo@localhost:5432/rimo'); c.autocommit=True; c.execute('CREATE EXTENSION IF NOT EXISTS vector')"
alembic upgrade head

# terminal 1 — API
uvicorn app.main:app --reload --port 8000
# terminal 2 — the autonomous worker
python -m app.orchestration.worker
```

**Frontend.**

```bash
cd frontend
npm install
RIMO_API_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

---

## Option C — Kubernetes (production)

Manifests live in `infra/k8s`, applied in order. They assume an `ingress-nginx` controller and `cert-manager`.

### 1. Build and push images

CI does this automatically on `main` (see `.github/workflows/ci.yml`), tagging `ghcr.io/<owner>/rimo-backend` and `rimo-frontend`. To build by hand:

```bash
docker build -t ghcr.io/<owner>/rimo-backend:latest ./backend
docker build -t ghcr.io/<owner>/rimo-frontend:latest ./frontend
docker push ghcr.io/<owner>/rimo-backend:latest
docker push ghcr.io/<owner>/rimo-frontend:latest
```

### 2. Create the namespace and secrets

The committed `Secret` is a **stub** — never put real values in git. Create the real one out-of-band:

```bash
kubectl apply -f infra/k8s/00-namespace-config.yaml   # namespace + configmap

kubectl -n rimo create secret generic rimo-secrets \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-..." \
  --from-literal=DATABASE_URL='postgresql+asyncpg://rimo:STRONGPASS@postgres:5432/rimo' \
  --from-literal=POSTGRES_PASSWORD='STRONGPASS' \
  --from-literal=OPENAI_API_KEY='' \
  --from-literal=GITHUB_APP_ID='...' \
  --from-literal=GITHUB_PRIVATE_KEY="$(cat github-app-key.pem)" \
  --from-literal=GITHUB_WEBHOOK_SECRET='...' \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 3. Apply the rest

```bash
kubectl apply -f infra/k8s/01-data.yaml            # Postgres + Redis (StatefulSets)
kubectl apply -f infra/k8s/02-api-worker.yaml      # migration Job + API + worker
kubectl apply -f infra/k8s/03-frontend-ingress.yaml # frontend + HPA + ingress
```

The migration `Job` enables pgvector and runs Alembic before the API and worker schedule. Re-running it on each release is idempotent (delete the completed job first with raw kubectl, or let the Helm hooks handle it).

### 4. Point DNS

Set `rimo.example.com` (in the ingress) to your load balancer, and cert-manager will issue TLS. The ingress is configured for SSE (read timeout 3600s, buffering off).

### Verify

```bash
kubectl -n rimo get pods
kubectl -n rimo logs deploy/rimo-worker -f
curl https://rimo.example.com/health
```

---

## Configuration reference

All settings are environment variables (`backend/app/core/config.py`). The ones you'll actually touch:

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | — (**required**) | JWT signing, min 32 chars |
| `ANTHROPIC_API_KEY` | — | Powers the agents |
| `DATABASE_URL` | local DSN | Async Postgres DSN |
| `REDIS_URL` | local | Event bus |
| `OPENAI_API_KEY` | empty | Embeddings; falls back to local |
| `DEFAULT_MODEL` | `claude-opus-4-8` | Reasoning model |
| `FAST_MODEL` | `claude-haiku-4-5-...` | Memory curation |
| `REQUIRE_HUMAN_APPROVAL_FOR_MERGE` | `true` | Gate merges |
| `REQUIRE_HUMAN_APPROVAL_FOR_DEPLOY` | `true` | Gate deploys |
| `ALLOW_REPO_DELETION` | `false` | Platform-wide kill switch |
| `MAX_CONCURRENT_PROJECTS` | `10` | Worker fan-out |
| `MAX_FILES_CHANGED_PER_PR` | `50` | Safety cap |

---

## Scaling and operations

- **API** is stateless — the HPA scales it 2→8 on CPU. Add replicas freely.
- **Worker** runs a **single replica** by design: project ticks are coordinated through database task leases, so one worker is correct and safe. Validate lease contention before scaling it out.
- **Postgres** is the one stateful dependency; back it up. For managed Postgres, ensure pgvector is available (most providers support it) and point `DATABASE_URL` at it instead of the in-cluster StatefulSet.
- **Crash recovery** is automatic: a worker that dies mid-task leaves an expiring lease; the next cycle returns the task to `ready` and retries.

---

## Security checklist

- [ ] `SECRET_KEY` is random and unique per environment — never the example value.
- [ ] Real secrets are in a `Secret` / vault, never committed.
- [ ] `ALLOW_REPO_DELETION=false` unless you have a specific reason.
- [ ] Human approval gates left **on** for merge and deploy in production.
- [ ] The GitHub App is scoped to only the repositories RiMo should touch.
- [ ] Secret scanning runs on every staged change (built in) — review findings surfaced by the Security agent.
