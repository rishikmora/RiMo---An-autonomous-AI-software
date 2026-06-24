# Security Policy

RiMo is designed to be pointed at real source repositories and to take
high-impact actions (commit, push, merge, deploy). Security is treated as a
first-class concern, not an afterthought.

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.x     | ✅         |
| < 1.0   | ❌         |

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Report privately to **security@rimo.dev** (or open a [GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories)
on the repository). Include:

- a description of the issue and its impact,
- steps to reproduce (a proof of concept if possible),
- affected version/commit.

You can expect an acknowledgement within **3 business days** and a status update
within **10 business days**. Coordinated disclosure is appreciated: please give
us a reasonable window to ship a fix before any public write-up.

## Security model & built-in safeguards

These are properties of the system, several of which are enforced by tests
(`backend/tests/test_orchestrator.py`, `test_safety.py`):

- **Human-in-the-loop gates.** Merges, deploys, and destructive actions require
  an explicit approval record. A PR cannot merge without one (proven by
  `test_merge_requires_approval_and_does_not_merge`).
- **Secret scanning.** Every staged file is scanned (pattern + entropy) before
  it can be committed; matches are redacted, never echoed.
- **Repository deletion is disabled** platform-wide by default and always
  requires approval even when enabled.
- **Hard financial cap.** `MAX_COST_USD_PER_PROJECT` pauses a project when its
  cumulative model spend reaches the ceiling (proven by
  `test_budget_cap_halts_project`).
- **Auth.** Short-lived access tokens (15 min) + rotating, revocable refresh
  tokens stored only as SHA-256 hashes. Refresh-token reuse is rejected.
- **Rate limiting.** Per-IP throttling on `/auth/login` and `/auth/register`
  (Redis-backed, fails open so a Redis blip can't take down auth).
- **CORS.** An explicit, env-driven origin allow-list — never a wildcard with
  credentials.
- **Secrets** are read from the environment / a secret store and never
  committed; `.env` is git-ignored.

## Hardening checklist for operators

- [ ] `SECRET_KEY` is unique per environment (generate with `openssl rand -hex 32`).
- [ ] `CORS_ORIGINS` lists only your real frontends.
- [ ] `MAX_COST_USD_PER_PROJECT` is set to a sane ceiling.
- [ ] `ALLOW_REPO_DELETION=false` unless you have a specific need.
- [ ] Merge/deploy approval gates left **on** in production.
- [ ] The GitHub App is scoped to only the repositories RiMo should touch.
