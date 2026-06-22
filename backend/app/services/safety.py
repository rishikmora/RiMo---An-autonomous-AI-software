"""Safety guardrails enforced on every write the agents perform.

Two responsibilities:

  1. **Secret detection** – scan file contents before they are committed and
     block anything that looks like a credential. This is defence-in-depth: it
     runs regardless of what the model "intends".
  2. **Destructive-action gating** – classify actions (merge, deploy, repo
     deletion, destructive migrations) and decide whether a human Approval is
     required given project autonomy settings.

These checks are deliberately conservative: a false positive blocks a commit
(recoverable), a false negative leaks a secret (not recoverable).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.core.config import settings
from app.models.enums import ApprovalKind

# Patterns for common credential formats. Extend freely; precision over recall
# is *not* the goal here — recall is.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_secret_key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai_key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("github_fine_grained", re.compile(r"github_pat_[A-Za-z0-9_]{60,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("stripe_key", re.compile(r"sk_live_[0-9a-zA-Z]{24,}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("generic_assignment", re.compile(
        r"(?i)(api[_-]?key|secret|passwd|password|token|credential)\s*[=:]\s*['\"][^'\"]{12,}['\"]"
    )),
]

# Files where a high-entropy string is expected and should not trip the scanner.
_ALLOWLIST_SUFFIXES = (".lock", ".min.js", ".map", ".snap")


@dataclass(slots=True)
class SecretFinding:
    path: str
    rule: str
    line: int
    preview: str


class SecretScanner:
    """Static secret detection over file contents."""

    def scan_file(self, path: str, content: str) -> list[SecretFinding]:
        if path.endswith(_ALLOWLIST_SUFFIXES):
            return []
        findings: list[SecretFinding] = []
        for lineno, line in enumerate(content.splitlines(), start=1):
            for rule, pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        SecretFinding(path, rule, lineno, _redact(line.strip()))
                    )
            # Entropy heuristic for unlabeled high-randomness tokens.
            for token in re.findall(r"[A-Za-z0-9/+=_\-]{32,}", line):
                if _shannon_entropy(token) > 4.5 and not _looks_like_hash_path(line):
                    findings.append(
                        SecretFinding(path, "high_entropy_string", lineno, _redact(token))
                    )
        return findings

    def scan_files(self, files: dict[str, str]) -> list[SecretFinding]:
        out: list[SecretFinding] = []
        for path, content in files.items():
            out.extend(self.scan_file(path, content))
        return out


@dataclass(slots=True)
class ActionDecision:
    allowed: bool
    requires_approval: bool
    approval_kind: ApprovalKind | None
    reason: str


class ActionGuard:
    """Decides whether a high-risk action may proceed autonomously."""

    def evaluate_merge(self, autonomy_level: int, review_score: float | None, checks_passing: bool) -> ActionDecision:
        if not checks_passing:
            return ActionDecision(False, False, None, "CI checks are not passing")
        if review_score is not None and review_score < 80:
            return ActionDecision(False, False, None, f"review score {review_score:.0f} below threshold 80")
        needs_approval = settings.require_human_approval_for_merge or autonomy_level < 3
        return ActionDecision(
            allowed=not needs_approval,
            requires_approval=needs_approval,
            approval_kind=ApprovalKind.MERGE if needs_approval else None,
            reason="auto-merge permitted" if not needs_approval else "human approval required for merge",
        )

    def evaluate_deploy(self, autonomy_level: int, environment: str) -> ActionDecision:
        # Production always needs approval unless explicitly running at full autonomy.
        prod = environment == "production"
        needs_approval = settings.require_human_approval_for_deploy or (prod and autonomy_level < 3)
        return ActionDecision(
            allowed=not needs_approval,
            requires_approval=needs_approval,
            approval_kind=ApprovalKind.DEPLOY if needs_approval else None,
            reason="auto-deploy permitted" if not needs_approval else f"approval required to deploy to {environment}",
        )

    def evaluate_repo_deletion(self) -> ActionDecision:
        if not settings.allow_repo_deletion:
            return ActionDecision(False, False, None, "repository deletion is disabled platform-wide")
        return ActionDecision(False, True, ApprovalKind.REPO_DELETE, "repository deletion always requires approval")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) for c in set(s)}
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _looks_like_hash_path(line: str) -> bool:
    # Lockfile integrity hashes, sourcemaps, git SHAs etc. are not secrets.
    return any(k in line.lower() for k in ("sha256", "sha512", "integrity", "sha-", "commit"))


def _redact(s: str) -> str:
    if len(s) <= 12:
        return "***"
    return f"{s[:4]}…{s[-2:]}"


secret_scanner = SecretScanner()
action_guard = ActionGuard()
