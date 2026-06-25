# Contributing to RiMo

Thanks for your interest in improving RiMo. This guide covers how to set up a
dev environment, run the checks, and what we expect in a pull request.

## Development setup

```bash
git clone https://github.com/rishikmora/rimo.git
cd rimo

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Frontend
cd ../frontend
npm install
```

You'll need a Postgres with the `pgvector` extension and a Redis instance. The
fastest way is the bundled compose stack:

```bash
docker compose up postgres redis -d
```

## Running the checks

Everything CI runs, you can run locally. **All of it must pass before a PR is
merged.**

```bash
# Backend — lint + tests (tests need Postgres + Redis reachable)
cd backend
ruff check app tests
pytest

# Frontend — typecheck, lint, build, tests
cd ../frontend
npm run typecheck
npm run lint
npm run build
npm test
```

The backend test suite includes orchestrator state-machine tests that run
against a real Postgres. If no database is reachable, DB-dependent tests skip
cleanly rather than fail — but please run them against a real database before
submitting changes to the orchestrator, worker, or API.

## Code style

- **Python**: `ruff` is the single source of truth (config in `pyproject.toml`).
  Correctness rules (`E`, `F`, `I`, `B`) are enforced. Type-annotate new code.
- **TypeScript**: `tsc --noEmit` must pass with zero errors; `eslint` clean.
- Prefer small, focused functions. Match the conventions of the file you're in.
- Every new behavior gets a test. Bug fixes get a regression test.

## Pull request expectations

1. **One logical change per PR.** Keep diffs reviewable.
2. **Describe the why,** not just the what. Link any issue it closes.
3. **Tests included** and passing locally (paste the output if helpful).
4. **No secrets, no credentials** in code, tests, or fixtures. Use env vars.
5. **Update docs** if you changed behavior, config, or the API surface.

## Areas that need extra care

- **`backend/app/orchestration/orchestrator.py`** — the state machine. Changes
  here must be covered by `tests/test_orchestrator.py`, especially anything
  touching leases, the approval gate, or the cost cap.
- **`backend/app/core/security.py`** — auth. Don't weaken token handling.
- **Anything that touches a real repository or spends money** — make sure the
  relevant safety gate still holds.

## Reporting security issues

Do **not** open a public issue. See [SECURITY.md](./SECURITY.md).
