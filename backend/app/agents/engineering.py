"""Engineering specialist agents.

Builder, Reviewer, QA, Security, and DevOps. These agents touch code: they read
the repository, stage file changes, and produce structured verdicts. All file
writes pass through the secret scanner in the toolset.
"""
from __future__ import annotations

from app.agents.base import AgentContext, BaseAgent
from app.agents.tools import build_engineering_toolset
from app.models.enums import AgentRole
from app.services.llm import ToolRegistry

_PROD_QUALITY_BAR = (
    "Code you write MUST be production-grade: fully typed, modular, documented, "
    "handling errors and edge cases, with no placeholders, TODOs, or stubbed logic. "
    "Never hard-code secrets — read configuration from environment variables."
)


class BuilderAgent(BaseAgent):
    role = AgentRole.BUILDER

    @property
    def system_prompt(self) -> str:
        return (
            "You are RiMo Builder, a senior software engineer. You implement tasks "
            "by reading the existing codebase to match its conventions, then writing "
            "or refactoring files to satisfy the acceptance criteria. You work "
            "incrementally: read first, then write. You verify your own work and run "
            "secret_scan before finishing.\n\n" + _PROD_QUALITY_BAR + "\n\n"
            "Use read_file/list_files to understand context, write_file to stage "
            "changes, and secret_scan to verify cleanliness. When done, summarise "
            "what you changed and why, and list the files you staged."
        )

    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        if ctx.github:
            build_engineering_toolset(
                registry, gh=ctx.github, project=ctx.project,
                workspace=ctx.workspace, branch=ctx.branch,
            )

    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        t = ctx.task
        criteria = "\n".join(f"- {c}" for c in t.acceptance_criteria) or "- (none specified)"
        notes = ctx.extra.get("architecture_notes", "")
        guidance = f"Architecture guidance:\n{notes}\n\n" if notes else ""
        return (
            f"Task ({t.kind.value}): {t.title}\n"
            f"Description: {t.description or ''}\n"
            f"Acceptance criteria:\n{criteria}\n"
            f"Working branch: {ctx.branch}\n"
            f"Primary language: {ctx.project.primary_language or 'infer from repo'}\n\n"
            f"{guidance}"
            f"{memory_context}\n\n"
            "Implement the task end-to-end. Read relevant files first, then stage all "
            "necessary changes and tests."
        )


class ReviewerAgent(BaseAgent):
    role = AgentRole.REVIEWER

    @property
    def system_prompt(self) -> str:
        return (
            "You are RiMo Reviewer, a meticulous staff engineer doing code review. "
            "You assess staged changes for correctness, readability, type safety, "
            "test coverage, security, and adherence to the acceptance criteria. You "
            "are constructive but uncompromising on quality. You give a numeric score "
            "from 0-100 and an explicit verdict.\n\n"
            "Read the staged files and any related code. Output ONLY a JSON object: "
            '{"score": int, "verdict": "approve|request_changes", "summary": str, '
            '"issues": [{"severity": "blocker|major|minor", "file": str, "comment": str}], '
            '"strengths": [str]}'
        )

    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        if ctx.github:
            build_engineering_toolset(
                registry, gh=ctx.github, project=ctx.project,
                workspace=ctx.workspace, branch=ctx.branch,
            )

    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        staged = "\n".join(f"- {p}" for p in ctx.workspace.staged) or "(none)"
        criteria = "\n".join(f"- {c}" for c in ctx.task.acceptance_criteria) or "- (none)"
        return (
            f"Reviewing changes for task: {ctx.task.title}\n"
            f"Acceptance criteria:\n{criteria}\n"
            f"Staged files:\n{staged}\n\n"
            f"{memory_context}\n\n"
            "Read each staged file (read_file returns staged content) plus any code it "
            "depends on, then deliver your review verdict. Approve only if it meets a "
            "production bar."
        )


class QAAgent(BaseAgent):
    role = AgentRole.QA

    @property
    def system_prompt(self) -> str:
        return (
            "You are RiMo QA, a test engineer. You ensure changes are covered by "
            "unit, integration, and where appropriate end-to-end tests. You write "
            "missing tests, reason about edge cases and failure modes, and predict "
            "whether the test suite will pass. You stage test files using write_file.\n\n"
            + _PROD_QUALITY_BAR + "\n\n"
            "Output ONLY JSON: {\"tests_added\": [str], \"coverage_assessment\": str, "
            "\"predicted_pass\": bool, \"gaps\": [str]}"
        )

    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        if ctx.github:
            build_engineering_toolset(
                registry, gh=ctx.github, project=ctx.project,
                workspace=ctx.workspace, branch=ctx.branch,
            )

    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        staged = "\n".join(f"- {p}" for p in ctx.workspace.staged) or "(none)"
        return (
            f"Task under test: {ctx.task.title}\n"
            f"Staged files:\n{staged}\n\n"
            f"{memory_context}\n\n"
            "Review the implementation, identify untested paths, and stage thorough "
            "tests following the repo's existing test framework and conventions."
        )


class SecurityAgent(BaseAgent):
    role = AgentRole.SECURITY

    @property
    def system_prompt(self) -> str:
        return (
            "You are RiMo Security, an application security engineer. You audit "
            "staged changes for vulnerabilities (injection, authn/authz flaws, "
            "insecure deserialisation, SSRF, secrets, unsafe dependencies, missing "
            "input validation) and confirm no credentials are committed. You map "
            "findings to severity and give concrete remediation.\n\n"
            "Run secret_scan and read the staged files. Output ONLY JSON: "
            '{"passed": bool, "findings": [{"severity": '
            '"critical|high|medium|low", "category": str, "file": str, '
            '"description": str, "remediation": str}], "secret_scan_clean": bool}'
        )

    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        if ctx.github:
            build_engineering_toolset(
                registry, gh=ctx.github, project=ctx.project,
                workspace=ctx.workspace, branch=ctx.branch,
            )

    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        staged = "\n".join(f"- {p}" for p in ctx.workspace.staged) or "(none)"
        return (
            f"Security audit for task: {ctx.task.title}\n"
            f"Staged files:\n{staged}\n\n"
            f"{memory_context}\n\n"
            "Run secret_scan first, then audit each staged file. Fail the audit on any "
            "critical or high severity finding, or any leaked secret."
        )


class DevOpsAgent(BaseAgent):
    role = AgentRole.DEVOPS

    @property
    def system_prompt(self) -> str:
        return (
            "You are RiMo DevOps, a platform engineer. You own deployment, "
            "monitoring, and rollbacks. You prepare deployment plans, container and "
            "CI configuration, health checks, and rollback procedures. You think "
            "about zero-downtime releases, observability, and failure recovery. You "
            "never deploy to production without the required approval.\n\n"
            + _PROD_QUALITY_BAR + "\n\n"
            "Output ONLY JSON: {\"plan\": [str], \"artifacts_staged\": [str], "
            "\"health_checks\": [str], \"rollback_strategy\": str, "
            "\"requires_approval\": bool}"
        )

    def build_tools(self, ctx: AgentContext, registry: ToolRegistry) -> None:
        if ctx.github:
            build_engineering_toolset(
                registry, gh=ctx.github, project=ctx.project,
                workspace=ctx.workspace, branch=ctx.branch,
            )

    def build_prompt(self, ctx: AgentContext, memory_context: str) -> str:
        env = ctx.extra.get("environment", "staging")
        return (
            f"Deployment task: {ctx.task.title}\n"
            f"Target environment: {env}\n"
            f"Project: {ctx.project.name} ({ctx.project.primary_language or 'polyglot'})\n\n"
            f"{memory_context}\n\n"
            "Produce a deployment plan and stage any required CI/container/config "
            "files. Specify health checks and a rollback strategy."
        )
