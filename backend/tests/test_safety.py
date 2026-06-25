"""Safety subsystem: secret detection and high-risk action gating."""
from __future__ import annotations

from app.models.enums import ApprovalKind
from app.services.safety import ActionGuard, SecretScanner


class TestSecretScanner:
    def setup_method(self) -> None:
        self.scanner = SecretScanner()

    def test_detects_aws_key(self) -> None:
        findings = self.scanner.scan_file("config.py", "key = 'AKIAIOSFODNN7EXAMPLE'")
        assert any(f.rule for f in findings)
        # The preview must be redacted, never the raw value.
        assert all("AKIAIOSFODNN7EXAMPLE" not in f.preview for f in findings)

    def test_detects_high_entropy_token(self) -> None:
        secret = "x7Kq9mPwT2vLnB4sF8jR1aD6gH0cE5yU3iO"  # noqa: S105 - test fixture
        findings = self.scanner.scan_file("app.py", f"token = '{secret}'")
        assert any(f.rule == "high_entropy_string" for f in findings)

    def test_ignores_lockfile_hashes(self) -> None:
        line = "  resolved sha512-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEf==="
        findings = self.scanner.scan_file("package.lock", line)
        assert findings == []

    def test_ignores_integrity_hashes(self) -> None:
        line = "integrity sha512-VeryLongIntegrityHashValueThatLooksRandom123456789=="
        findings = self.scanner.scan_file("app.py", line)
        assert findings == []

    def test_clean_code_has_no_findings(self) -> None:
        code = "def add(a, b):\n    return a + b\n"
        assert self.scanner.scan_file("math.py", code) == []

    def test_scan_files_aggregates(self) -> None:
        files = {
            "a.py": "AKIAIOSFODNN7EXAMPLE",
            "b.py": "clean = 1",
        }
        findings = self.scanner.scan_files(files)
        assert any(f.path == "a.py" for f in findings)
        assert all(f.path != "b.py" for f in findings)


class TestActionGuard:
    def setup_method(self) -> None:
        self.guard = ActionGuard()

    def test_merge_blocked_when_checks_failing(self) -> None:
        decision = self.guard.evaluate_merge(autonomy_level=3, review_score=95, checks_passing=False)
        assert decision.allowed is False
        assert decision.requires_approval is False
        assert "checks" in decision.reason.lower()

    def test_merge_blocked_on_low_review_score(self) -> None:
        decision = self.guard.evaluate_merge(autonomy_level=3, review_score=60, checks_passing=True)
        assert decision.allowed is False
        assert "below threshold" in decision.reason

    def test_merge_requires_approval_by_default(self) -> None:
        # Default settings require human approval for merges regardless of score.
        decision = self.guard.evaluate_merge(autonomy_level=2, review_score=95, checks_passing=True)
        assert decision.requires_approval is True
        assert decision.approval_kind is ApprovalKind.MERGE

    def test_deploy_requires_approval(self) -> None:
        decision = self.guard.evaluate_deploy(autonomy_level=2, environment="production")
        assert decision.requires_approval is True
        assert decision.approval_kind is ApprovalKind.DEPLOY

    def test_repo_deletion_disabled_by_default(self) -> None:
        decision = self.guard.evaluate_repo_deletion()
        assert decision.allowed is False
