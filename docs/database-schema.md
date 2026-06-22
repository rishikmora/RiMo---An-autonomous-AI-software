# RiMo — Database Schema

PostgreSQL 16 with the `pgvector` extension. The schema is normalized around five aggregates and is created/migrated by Alembic (`backend/migrations`). Semantic memory is powered by a `vector(1536)` column with an HNSW index.

Apply with:

```bash
alembic upgrade head        # after CREATE EXTENSION IF NOT EXISTS vector
```

---

## Entity relationships

```
users ──1:N──▶ projects
                  │
                  ├──1:N──▶ agents            (one row per role; 10 per project)
                  ├──1:N──▶ tasks ──1:N──▶ agent_runs
                  │            └──1:1──▶ pull_requests ──1:N──▶ deployments
                  ├──1:N──▶ memory_records    (pgvector)
                  ├──1:N──▶ approvals
                  └──1:N──▶ activity_events
```

All child rows cascade-delete with their project; deleting a user cascades to their projects.

---

## Tables

### users
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| email | VARCHAR(320) | NOT NULL, **unique** |
| full_name | VARCHAR(255) | |
| hashed_password | VARCHAR(255) | NOT NULL (bcrypt) |
| is_active | BOOLEAN | NOT NULL |
| is_superuser | BOOLEAN | NOT NULL |
| github_installation_id | VARCHAR(64) | links the user's GitHub App install |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL |

### projects
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| owner_id | UUID | NOT NULL → users.id |
| name | VARCHAR(255) | NOT NULL |
| slug | VARCHAR(255) | NOT NULL, indexed; unique per owner |
| description | TEXT | |
| status | ENUM | draft, analyzing, active, paused, blocked, archived |
| repo_full_name | VARCHAR(512) | `owner/repo` |
| repo_url | VARCHAR(1024) | |
| default_branch | VARCHAR(255) | NOT NULL, default `main` |
| primary_language | VARCHAR(64) | detected by the analyzer |
| mission | TEXT | owned by the CEO agent |
| objectives | JSONB | NOT NULL, prioritized objective list |
| autonomy_level | INTEGER | 0=manual … 3=full |
| is_running | BOOLEAN | NOT NULL, indexed — the worker's selector |
| architecture_summary | TEXT | cached codebase analysis |
| file_tree | JSONB | cached repository structure |
| metrics | JSONB | rolling project metrics |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL |

**Constraint:** `UNIQUE(owner_id, slug)`.

### agents
A per-project instance of each specialist role. Exactly ten rows per project.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| project_id | UUID | NOT NULL → projects.id |
| role | ENUM | ceo, research, planner, architect, builder, reviewer, qa, security, devops, memory |
| status | ENUM | idle, thinking, working, waiting, error, offline |
| current_task_id | UUID | → tasks.id (SET NULL) |
| last_heartbeat | TIMESTAMPTZ | liveness for the dashboard |
| total_runs | INTEGER | lifetime executions |
| total_tokens | BIGINT | lifetime token spend |
| config | JSONB | per-agent overrides |

**Constraints:** `UNIQUE(project_id, role)`; composite index on `(status, role)`.

### tasks
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| project_id | UUID | NOT NULL → projects.id |
| parent_id | UUID | → tasks.id (subtasks) |
| title | VARCHAR(512) | NOT NULL |
| description | TEXT | |
| kind | ENUM | feature, bugfix, refactor, test, security, performance, docs, infra, research |
| status | ENUM | backlog, ready, in_progress, in_review, blocked, done, cancelled, failed |
| priority | ENUM | critical(0), high(1), medium(2), low(3) |
| complexity | INTEGER | story points 1–13 |
| assigned_role | ENUM | which specialist owns it |
| branch_name | VARCHAR(255) | working branch |
| depends_on | JSONB | list of task ids |
| acceptance_criteria | JSONB | list of strings |
| attempts | INTEGER | retry counter |
| lease_expires_at | TIMESTAMPTZ | **crash recovery** — expired leases return to `ready` |
| result | JSONB | structured outcome |
| github_issue_number | INTEGER | linked GitHub issue |

**Index:** `ix_task_queue (project_id, status, priority)` — the orchestrator's work-selection query.

### agent_runs
One execution of an agent against a task (a single reasoning loop), with the full transcript.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| task_id | UUID | NOT NULL → tasks.id |
| agent_role | ENUM | which agent ran |
| started_at / finished_at | TIMESTAMPTZ | |
| success | BOOLEAN | nullable until finished |
| iterations | INTEGER | loop iterations used |
| input_tokens / output_tokens | INTEGER | per-run spend |
| model | VARCHAR(128) | model string used |
| transcript | JSONB | list of step dicts (text + tool calls) |
| error | TEXT | failure detail |

### pull_requests
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| project_id | UUID | NOT NULL → projects.id |
| task_id | UUID | → tasks.id (1:1) |
| number | INTEGER | NOT NULL, GitHub PR number |
| title / body | VARCHAR/TEXT | |
| head_branch / base_branch | VARCHAR(255) | |
| status | ENUM | open, approved, changes_requested, merged, closed |
| files_changed / additions / deletions | INTEGER | diff stats |
| review_summary | TEXT | Reviewer agent output |
| review_score | FLOAT | 0–100; merge gate threshold is 80 |
| checks_passing | BOOLEAN | CI status |
| merge_commit_sha | VARCHAR(64) | |
| merged_at | TIMESTAMPTZ | |

**Constraint:** `UNIQUE(project_id, number)`.

### deployments
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| project_id | UUID | NOT NULL → projects.id |
| environment | VARCHAR(64) | staging, production, … |
| commit_sha | VARCHAR(64) | |
| status | ENUM | queued, running, succeeded, failed, rolled_back |
| url | VARCHAR(1024) | deployed URL |
| logs | TEXT | |
| rolled_back_from | UUID | prior deployment this rolled back |
| duration_seconds | FLOAT | |

### memory_records
Long-term, vector-indexed knowledge for cross-project learning.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| project_id | UUID | → projects.id (nullable: global memories) |
| kind | ENUM | architecture_decision, bug_fix, user_preference, project_fact, successful_implementation, lesson_learned |
| title | VARCHAR(512) | NOT NULL |
| content | TEXT | NOT NULL |
| meta | JSONB | provenance, tags |
| importance | FLOAT | 0–1, drives retention |
| access_count | INTEGER | recall frequency |
| **embedding** | **VECTOR(1536)** | NOT NULL |

**Index:** `ix_memory_embedding_hnsw` — HNSW with `vector_cosine_ops`, `m=16`, `ef_construction=64`.

```sql
-- The recall query (simplified):
SELECT id, title, content
FROM memory_records
WHERE project_id = :pid OR project_id IS NULL
ORDER BY embedding <=> :query_vector   -- cosine distance
LIMIT :k;
```

### approvals
Human-in-the-loop gates for high-risk actions.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| project_id | UUID | NOT NULL → projects.id |
| kind | ENUM | merge, deploy, repo_delete, destructive_migration |
| subject_id | UUID | the PR / deployment awaiting approval |
| summary | TEXT | NOT NULL, human-readable |
| payload | JSONB | action detail |
| approved | BOOLEAN | **NULL = pending**, true/false = decided |
| decided_by | UUID | → users.id |
| decided_at | TIMESTAMPTZ | |

### activity_events
Append-only event stream powering the dashboard timeline. Auto-incrementing BIGINT PK (cheap, ordered, high-volume).

| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT | PK, autoincrement |
| project_id | UUID | NOT NULL → projects.id |
| agent_role | ENUM | nullable (system events) |
| event_type | VARCHAR(64) | indexed |
| message | TEXT | NOT NULL |
| data | JSONB | structured payload |
| created_at | TIMESTAMPTZ | indexed (timeline ordering) |

---

## Design notes

- **Enums as `VARCHAR` (non-native).** Domain enums inherit `(str, Enum)` and are stored as strings (`native_enum=False`), so adding a value never requires a Postgres `ALTER TYPE` migration — only application code changes.
- **JSONB for flexible substructure.** Objectives, acceptance criteria, transcripts, and metrics evolve in shape; JSONB keeps them queryable without rigid columns.
- **Leases over locks.** Task ownership is a time-bound `lease_expires_at`, not a row lock — so a crashed worker self-heals: the lease lapses and the task is retried.
- **One store, two jobs.** Postgres holds both transactional state and semantic memory (via pgvector), avoiding a separate vector database.
