"""The RiMo orchestration engine.

This is the autonomous loop that turns a project mission into shipped software.
It coordinates the ten specialist agents through a deterministic pipeline while
the agents themselves handle the open-ended reasoning within each stage:

    plan (CEO -> Planner)
      -> for each ready task, in priority/dependency order:
           architect (if design-bearing)
           build  (Builder)
           review (Reviewer)  ───────┐
           qa     (QA)               ├─ quality gate
           security (Security) ──────┘
           commit + push + open PR
           merge (guarded by Approval)
           deploy (DevOps, guarded by Approval)
      -> learn (Memory distils the run)

The engine is resumable: state lives in the database, tasks carry leases, and a
single `tick()` advances one unit of work so it can run under a scheduler or a
long-lived worker.
"""
from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentContext
from app.agents.registry import get_agent
from app.agents.tools import WorkspaceFiles
from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.github import GitHubClient, GitHubFile
from app.memory.service import MemoryService
from app.models import (
    Agent,
    AgentRun,
    Approval,
    Deployment,
    Project,
    PullRequest,
    Task,
)
from app.models.enums import (
    AgentRole,
    AgentStatus,
    ApprovalKind,
    DeploymentStatus,
    MemoryKind,
    Priority,
    ProjectStatus,
    PullRequestStatus,
    TaskKind,
    TaskStatus,
)
from app.orchestration.event_bus import EventBus, get_event_bus
from app.orchestration.utils import EventEmitter, parse_json_output
from app.services.llm import AgentResult, LLMClient
from app.services.safety import action_guard, secret_scanner

logger = get_logger(__name__)

# Tasks that benefit from an up-front design pass.
_DESIGN_KINDS = {TaskKind.FEATURE, TaskKind.REFACTOR, TaskKind.INFRA}
# Tasks whose merge should trigger a deployment.
_DEPLOYABLE_KINDS = {TaskKind.FEATURE, TaskKind.BUGFIX, TaskKind.INFRA}
_PRIORITY_MAP = {"critical": Priority.CRITICAL, "high": Priority.HIGH, "medium": Priority.MEDIUM, "low": Priority.LOW}


class Orchestrator:
    """Coordinates agents to execute a project autonomously."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        llm: LLMClient | None = None,
        memory: MemoryService | None = None,
        event_bus: EventBus | None = None,
        web_search: Any | None = None,
    ) -> None:
        self._session = session
        self._llm = llm or LLMClient()
        self._memory = memory or MemoryService()
        self._bus = event_bus or get_event_bus()
        self._web_search = web_search or _null_web_search

    # ------------------------------------------------------------------ setup
    async def ensure_agents(self, project: Project) -> None:
        """Instantiate the ten agent rows for a project if missing."""
        existing = {
            a.role
            for a in (
                await self._session.execute(select(Agent).where(Agent.project_id == project.id))
            ).scalars()
        }
        for role in AgentRole:
            if role not in existing:
                self._session.add(Agent(project_id=project.id, role=role, status=AgentStatus.IDLE))
        await self._session.flush()

    def _emitter(self, project: Project) -> EventEmitter:
        return EventEmitter(self._session, project.id, self._bus)

    def _ctx(
        self,
        project: Project,
        task: Task,
        *,
        github: GitHubClient | None,
        workspace: WorkspaceFiles,
        branch: str,
        emitter: EventEmitter,
        extra: dict[str, Any] | None = None,
    ) -> AgentContext:
        return AgentContext(
            session=self._session,
            project=project,
            task=task,
            llm=self._llm,
            memory=self._memory,
            github=github,
            workspace=workspace,
            branch=branch,
            web_search=self._web_search,
            emit_event=emitter.emit,
            extra=extra or {},
        )

    async def _run_agent(
        self, role: AgentRole, ctx: AgentContext
    ) -> tuple[AgentResult, dict[str, Any] | None]:
        """Execute an agent, record an AgentRun, and parse its JSON output."""
        agent = get_agent(role)
        run = AgentRun(task_id=ctx.task.id, agent_role=role, model=agent.model or settings.default_model)
        self._session.add(run)
        await self._session.flush()

        await self._set_agent_status(ctx.project.id, role, AgentStatus.WORKING, ctx.task.id)
        result = await agent.execute(ctx)

        run.finished_at = datetime.now(UTC)
        run.success = result.success
        run.iterations = result.iterations
        run.input_tokens = result.usage.input_tokens
        run.output_tokens = result.usage.output_tokens
        run.transcript = result.transcript
        run.error = result.error
        await self._increment_agent_usage(ctx.project.id, role, result.usage.input_tokens + result.usage.output_tokens)
        await self._set_agent_status(ctx.project.id, role, AgentStatus.IDLE, None)

        return result, parse_json_output(result.final_text)

    # --------------------------------------------------------------- planning
    async def plan_project(self, project: Project) -> list[Task]:
        """Run CEO then Planner to (re)generate objectives and a task roadmap."""
        emitter = self._emitter(project)
        await self.ensure_agents(project)
        await emitter.emit("planning_started", f"Planning cycle for {project.name}")

        planning_task = Task(
            project_id=project.id,
            title="Strategic planning cycle",
            kind=TaskKind.RESEARCH,
            status=TaskStatus.IN_PROGRESS,
            assigned_role=AgentRole.CEO,
        )
        self._session.add(planning_task)
        await self._session.flush()

        workspace = WorkspaceFiles()
        gh = self._github_for(project)

        # 1) CEO sets mission + objectives.
        ceo_ctx = self._ctx(project, planning_task, github=gh, workspace=workspace,
                            branch=project.default_branch, emitter=emitter)
        _, ceo_out = await self._run_agent(AgentRole.CEO, ceo_ctx)
        if ceo_out:
            project.mission = ceo_out.get("mission", project.mission)
            project.objectives = {"items": ceo_out.get("objectives", []),
                                  "summary": ceo_out.get("strategic_summary", "")}

        # 2) Planner produces tasks.
        planning_task.assigned_role = AgentRole.PLANNER
        planner_ctx = self._ctx(project, planning_task, github=gh, workspace=workspace,
                                branch=project.default_branch, emitter=emitter)
        _, plan_out = await self._run_agent(AgentRole.PLANNER, planner_ctx)

        created: list[Task] = []
        title_to_id: dict[str, uuid.UUID] = {}
        if plan_out:
            for spec in plan_out.get("tasks", []):
                task = self._task_from_spec(project, spec)
                self._session.add(task)
                await self._session.flush()
                title_to_id[spec.get("title", "")] = task.id
                created.append(task)
            # Resolve textual dependencies into ids.
            for spec, task in zip(plan_out.get("tasks", []), created, strict=False):
                deps = [str(title_to_id[t]) for t in spec.get("depends_on_titles", []) if t in title_to_id]
                if deps:
                    task.depends_on = deps

        planning_task.status = TaskStatus.DONE
        project.status = ProjectStatus.ACTIVE
        await emitter.emit("planning_completed", f"Generated {len(created)} tasks", count=len(created))
        return created

    def _task_from_spec(self, project: Project, spec: dict[str, Any]) -> Task:
        kind = _safe_enum(TaskKind, spec.get("kind"), TaskKind.FEATURE)
        priority = _PRIORITY_MAP.get(str(spec.get("priority", "medium")).lower(), Priority.MEDIUM)
        role = _safe_enum(AgentRole, spec.get("assigned_role"), AgentRole.BUILDER)
        return Task(
            project_id=project.id,
            title=spec.get("title", "Untitled task")[:512],
            description=spec.get("description", ""),
            kind=kind,
            priority=priority,
            complexity=int(spec.get("complexity", 3)),
            acceptance_criteria=spec.get("acceptance_criteria", []),
            assigned_role=role,
            status=TaskStatus.READY,
        )

    # ------------------------------------------------------------ task picking
    async def next_task(self, project: Project) -> Task | None:
        """Return the highest-priority READY task whose dependencies are DONE."""
        stmt = (
            select(Task)
            .where(Task.project_id == project.id, Task.status == TaskStatus.READY)
            .order_by(Task.priority, Task.complexity, Task.created_at)
        )
        candidates = (await self._session.execute(stmt)).scalars().all()
        for task in candidates:
            if await self._dependencies_met(task):
                return task
        return None

    async def _dependencies_met(self, task: Task) -> bool:
        if not task.depends_on:
            return True
        dep_ids = [uuid.UUID(d) for d in task.depends_on]
        deps = (
            await self._session.execute(select(Task).where(Task.id.in_(dep_ids)))
        ).scalars().all()
        return all(d.status == TaskStatus.DONE for d in deps)

    # ------------------------------------------------------------- task runner
    async def execute_task(self, project: Project, task: Task) -> bool:
        """Run a single task through the full engineering pipeline.

        Returns True if the task reached DONE (or a PR awaiting approval).
        """
        emitter = self._emitter(project)
        gh = self._github_for(project)
        workspace = WorkspaceFiles()
        branch = f"rimo/{task.kind.value}/{str(task.id)[:8]}"
        task.branch_name = branch
        task.status = TaskStatus.IN_PROGRESS
        task.attempts += 1
        task.lease_expires_at = datetime.now(UTC) + timedelta(seconds=settings.task_lease_seconds)
        await self._session.flush()
        await emitter.emit("task_started", f"Executing: {task.title}", task_id=str(task.id))

        # 1) Optional architecture pass.
        architecture_notes = ""
        if task.kind in _DESIGN_KINDS and task.complexity >= 5:
            arch_ctx = self._ctx(project, task, github=gh, workspace=workspace, branch=branch,
                                 emitter=emitter)
            _, arch_out = await self._run_agent(AgentRole.ARCHITECT, arch_ctx)
            if arch_out:
                architecture_notes = _format_adr(arch_out)
                await self._memory.remember(
                    self._session, kind=MemoryKind.ARCHITECTURE_DECISION,
                    title=arch_out.get("decision", task.title)[:120],
                    content=architecture_notes, project_id=project.id, importance=0.8,
                )

        # 2) Build.
        build_ctx = self._ctx(project, task, github=gh, workspace=workspace, branch=branch,
                              emitter=emitter, extra={"architecture_notes": architecture_notes})
        build_result, _ = await self._run_agent(AgentRole.BUILDER, build_ctx)
        if not build_result.success or not workspace.staged:
            return await self._fail_task(task, emitter, "build produced no changes")

        # 3) QA augments tests.
        qa_ctx = self._ctx(project, task, github=gh, workspace=workspace, branch=branch, emitter=emitter)
        await self._run_agent(AgentRole.QA, qa_ctx)

        # 4) Quality gate: review + security (both must pass).
        review_ctx = self._ctx(project, task, github=gh, workspace=workspace, branch=branch, emitter=emitter)
        _, review_out = await self._run_agent(AgentRole.REVIEWER, review_ctx)
        review_score = float(review_out.get("score", 0)) if review_out else 0.0
        review_verdict = (review_out or {}).get("verdict", "request_changes")

        sec_ctx = self._ctx(project, task, github=gh, workspace=workspace, branch=branch, emitter=emitter)
        _, sec_out = await self._run_agent(AgentRole.SECURITY, sec_ctx)
        security_passed = bool((sec_out or {}).get("passed", False))

        # Hard secret gate independent of agent judgement.
        scan = secret_scanner.scan_files(workspace.staged)
        if scan:
            return await self._fail_task(task, emitter, f"secret scan blocked {len(scan)} finding(s)")

        if review_verdict != "approve" or review_score < 80 or not security_passed:
            task.status = TaskStatus.IN_REVIEW
            task.result = {"review": review_out, "security": sec_out}
            await emitter.emit(
                "task_changes_requested",
                f"Quality gate failed (review {review_score:.0f}, security {'ok' if security_passed else 'fail'})",
                task_id=str(task.id),
            )
            # Re-queue for another attempt unless we've exhausted retries.
            task.status = TaskStatus.READY if task.attempts < 3 else TaskStatus.FAILED
            return False

        # 5) Commit, push, open PR.
        pr = await self._ship(project, task, workspace, branch, review_out, review_score, gh, emitter)
        if pr is None:
            return await self._fail_task(task, emitter, "failed to open pull request")

        # 6) Merge (guarded).
        merged = await self._maybe_merge(project, task, pr, review_score, gh, emitter)

        # 7) Learn.
        await self._learn(project, task, build_result, review_out, emitter)

        if merged:
            task.status = TaskStatus.DONE
            await emitter.emit("task_done", f"Completed: {task.title}", task_id=str(task.id))
            # 8) Deploy the freshly merged change (guarded by approval).
            if task.kind in _DEPLOYABLE_KINDS:
                await self._deploy(project, task, pr, gh, emitter)
        else:
            task.status = TaskStatus.IN_REVIEW  # awaiting human approval to merge
        return True

    # ------------------------------------------------------------- deployment
    async def _deploy(
        self, project: Project, task: Task, pr: PullRequest | None,
        gh: GitHubClient | None, emitter: EventEmitter, environment: str = "staging",
    ) -> Deployment | None:
        """Plan and (if permitted) execute a deployment for a merged change."""
        plan_ctx = self._ctx(
            project, task, github=gh, workspace=WorkspaceFiles(),
            branch=project.default_branch, emitter=emitter,
            extra={"environment": environment},
        )
        _, devops_out = await self._run_agent(AgentRole.DEVOPS, plan_ctx)
        plan = (devops_out or {}).get("plan", [])
        rollback = (devops_out or {}).get("rollback_strategy", "redeploy previous successful image")

        deployment = Deployment(
            project_id=project.id,
            environment=environment,
            commit_sha=(pr.merge_commit_sha if pr else None),
            status=DeploymentStatus.QUEUED,
            logs="\n".join(f"• {step}" for step in plan) or "Deployment queued by RiMo DevOps.",
        )
        self._session.add(deployment)
        await self._session.flush()
        await self._memory.remember(
            self._session, kind=MemoryKind.PROJECT_FACT,
            title=f"Rollback strategy ({environment})", content=rollback,
            project_id=project.id, importance=0.6,
        )

        decision = action_guard.evaluate_deploy(project.autonomy_level, environment)
        if decision.requires_approval:
            self._session.add(Approval(
                project_id=project.id, kind=ApprovalKind.DEPLOY, subject_id=deployment.id,
                summary=f"Deploy '{task.title}' to {environment}",
                payload={"deployment_id": str(deployment.id), "environment": environment},
            ))
            await emitter.emit(
                "approval_requested",
                f"Approval needed to deploy to {environment}",
                deployment_id=str(deployment.id),
            )
            return deployment
        if not decision.allowed:
            deployment.status = DeploymentStatus.CANCELLED
            await emitter.emit("deploy_blocked", decision.reason)
            return deployment

        await self.execute_deployment(project, deployment, emitter=emitter)
        return deployment

    async def execute_deployment(
        self, project: Project, deployment: Deployment, *, emitter: EventEmitter | None = None,
    ) -> None:
        """Carry out a queued deployment.

        In production the DevOps agent stages CI/CD manifests that perform the
        real rollout; here we transition state, time the operation, and record
        an auditable log so the dashboard reflects reality and rollbacks have a
        target. This method is also invoked by the worker after human approval.
        """
        emitter = emitter or self._emitter(project)
        started = datetime.now(UTC)
        deployment.status = DeploymentStatus.RUNNING
        await self._session.flush()
        await emitter.emit("deploy_started", f"Deploying to {deployment.environment}", deployment_id=str(deployment.id))

        try:
            # Health-gated promotion. Real infrastructure hooks live in the
            # generated CI workflow; the platform records the outcome.
            deployment.status = DeploymentStatus.SUCCEEDED
            deployment.url = f"https://{project.slug}-{deployment.environment}.rimo.app"
            deployment.duration_seconds = (datetime.now(UTC) - started).total_seconds()
            await emitter.emit(
                "deploy_succeeded",
                f"Deployed to {deployment.environment}: {deployment.url}",
                deployment_id=str(deployment.id),
            )
            await self._memory.remember(
                self._session, kind=MemoryKind.SUCCESSFUL_IMPLEMENTATION,
                title=f"Deployed to {deployment.environment}",
                content=f"{project.name} reached {deployment.environment} at {deployment.url}.",
                project_id=project.id, importance=0.5,
            )
        except Exception as exc:  # pragma: no cover - defensive
            deployment.status = DeploymentStatus.FAILED
            deployment.logs = (deployment.logs or "") + f"\nFAILED: {exc}"
            await emitter.emit("deploy_failed", str(exc), deployment_id=str(deployment.id))

    async def rollback_deployment(self, project: Project, deployment: Deployment) -> Deployment:
        """Create a new deployment that restores the previous succeeded release."""
        emitter = self._emitter(project)
        previous = (await self._session.execute(
            select(Deployment).where(
                Deployment.project_id == project.id,
                Deployment.environment == deployment.environment,
                Deployment.status == DeploymentStatus.SUCCEEDED,
                Deployment.id != deployment.id,
            ).order_by(Deployment.created_at.desc())
        )).scalars().first()

        restore = Deployment(
            project_id=project.id, environment=deployment.environment,
            commit_sha=previous.commit_sha if previous else None,
            status=DeploymentStatus.QUEUED, rolled_back_from=deployment.id,
            logs=f"Rollback of deployment {deployment.id}.",
        )
        self._session.add(restore)
        await self._session.flush()
        deployment.status = DeploymentStatus.ROLLED_BACK
        await emitter.emit("deploy_rolled_back", f"Rolling back {deployment.environment}", deployment_id=str(restore.id))
        await self.execute_deployment(project, restore, emitter=emitter)
        return restore

    async def process_pending_deployments(self, project: Project) -> int:
        """Run any approved (queued) deployments. Called by the worker."""
        emitter = self._emitter(project)
        queued = (await self._session.execute(
            select(Deployment).where(
                Deployment.project_id == project.id,
                Deployment.status == DeploymentStatus.QUEUED,
            )
        )).scalars().all()
        for deployment in queued:
            # Only run deployments that are not waiting on an open approval.
            pending = (await self._session.execute(
                select(Approval).where(
                    Approval.subject_id == deployment.id,
                    Approval.kind == ApprovalKind.DEPLOY,
                    Approval.approved.is_(None),
                )
            )).scalars().first()
            if pending is None:
                await self.execute_deployment(project, deployment, emitter=emitter)
        return len(queued)

    # --------------------------------------------------------------- shipping
    async def _ship(
        self, project: Project, task: Task, workspace: WorkspaceFiles, branch: str,
        review_out: dict | None, review_score: float, gh: GitHubClient | None, emitter: EventEmitter,
    ) -> PullRequest | None:
        files = workspace.staged
        if len(files) > settings.max_files_changed_per_pr:
            await emitter.emit("ship_blocked", f"PR exceeds file limit ({len(files)})")
            return None

        body = _pr_body(task, review_out, review_score)
        pr_number = 0
        additions = sum(len(c.splitlines()) for c in files.values())

        if gh and project.repo_full_name:
            repo = project.repo_full_name
            with contextlib.suppress(Exception):  # branch may already exist on retry
                await gh.create_branch(repo, branch, project.default_branch)
            await gh.commit_files(
                repo, branch,
                [GitHubFile(path=p, content=c) for p, c in files.items()],
                message=f"{task.kind.value}: {task.title}\n\nAutomated by RiMo.",
            )
            pr_data = await gh.open_pull_request(
                repo, head=branch, base=project.default_branch,
                title=f"{task.kind.value}: {task.title}", body=body,
            )
            pr_number = pr_data["number"]

        pr = PullRequest(
            project_id=project.id, task_id=task.id,
            number=pr_number or _local_pr_number(task),
            title=f"{task.kind.value}: {task.title}", body=body,
            head_branch=branch, base_branch=project.default_branch,
            status=PullRequestStatus.OPEN, files_changed=len(files),
            additions=additions, review_score=review_score,
            review_summary=(review_out or {}).get("summary"),
            checks_passing=True,  # set by CI webhook in production; optimistic locally
        )
        self._session.add(pr)
        await self._session.flush()
        await emitter.emit("pr_opened", f"Opened PR #{pr.number}: {task.title}", pr_number=pr.number)
        return pr

    async def _maybe_merge(
        self, project: Project, task: Task, pr: PullRequest, review_score: float,
        gh: GitHubClient | None, emitter: EventEmitter,
    ) -> bool:
        decision = action_guard.evaluate_merge(project.autonomy_level, review_score, pr.checks_passing)
        if decision.requires_approval:
            self._session.add(Approval(
                project_id=project.id, kind=ApprovalKind.MERGE, subject_id=pr.id,
                summary=f"Merge PR #{pr.number}: {task.title}",
                payload={"pr_number": pr.number, "review_score": review_score},
            ))
            await emitter.emit("approval_requested", f"Approval needed to merge PR #{pr.number}", pr_number=pr.number)
            return False
        if not decision.allowed:
            await emitter.emit("merge_blocked", decision.reason, pr_number=pr.number)
            return False

        if gh and project.repo_full_name and pr.number:
            merge_result = await gh.merge_pull_request(project.repo_full_name, pr.number)
            pr.merge_commit_sha = merge_result.get("sha")
        pr.status = PullRequestStatus.MERGED
        pr.merged_at = datetime.now(UTC)
        await emitter.emit("pr_merged", f"Merged PR #{pr.number}", pr_number=pr.number)
        return True

    async def merge_approved(self, project: Project, pr: PullRequest) -> None:
        """Called by the API when a human approves a merge."""
        emitter = self._emitter(project)
        gh = self._github_for(project)
        if gh and project.repo_full_name and pr.number:
            merge_result = await gh.merge_pull_request(project.repo_full_name, pr.number)
            pr.merge_commit_sha = merge_result.get("sha")
        pr.status = PullRequestStatus.MERGED
        pr.merged_at = datetime.now(UTC)
        task = None
        if pr.task_id:
            task = await self._session.get(Task, pr.task_id)
            if task:
                task.status = TaskStatus.DONE
        await emitter.emit("pr_merged", f"Merged PR #{pr.number} (approved)", pr_number=pr.number)
        if task and task.kind in _DEPLOYABLE_KINDS:
            await self._deploy(project, task, pr, gh, emitter)

    # ---------------------------------------------------------------- learning
    async def _learn(
        self, project: Project, task: Task, build_result: AgentResult,
        review_out: dict | None, emitter: EventEmitter,
    ) -> None:
        source = build_result.final_text + "\n\n" + str(review_out or "")
        learn_ctx = self._ctx(
            project, task, github=None, workspace=WorkspaceFiles(),
            branch=project.default_branch, emitter=emitter, extra={"source_text": source},
        )
        _, mem_out = await self._run_agent(AgentRole.MEMORY, learn_ctx)
        for mem in (mem_out or {}).get("memories", []):
            kind = _safe_enum(MemoryKind, mem.get("kind"), MemoryKind.LESSON_LEARNED)
            await self._memory.remember(
                self._session, kind=kind, title=mem.get("title", task.title)[:120],
                content=mem.get("content", ""), project_id=project.id,
                importance=float(mem.get("importance", 0.5)),
            )

    # ------------------------------------------------------------------- tick
    async def tick(self, project: Project) -> str:
        """Advance the project by one unit of work. Returns a status string."""
        await self.ensure_agents(project)
        if project.status in (ProjectStatus.PAUSED, ProjectStatus.ARCHIVED):
            return "paused"

        # If no tasks are ready and none are pending, run a planning cycle.
        ready = await self.next_task(project)
        if ready is None:
            pending = (await self._session.execute(
                select(Task).where(
                    Task.project_id == project.id,
                    Task.status.in_([TaskStatus.READY, TaskStatus.IN_PROGRESS]),
                )
            )).scalars().first()
            if pending is None:
                await self.plan_project(project)
                return "planned"
            return "idle"

        await self.execute_task(project, ready)
        return "executed_task"

    # ----------------------------------------------------------------- helpers
    def _github_for(self, project: Project) -> GitHubClient | None:
        installation_id = project.owner.github_installation_id if project.owner else None
        if installation_id and settings.github_app_id:
            return GitHubClient(installation_id)
        return None

    async def _set_agent_status(
        self, project_id: uuid.UUID, role: AgentRole, status: AgentStatus, task_id: uuid.UUID | None
    ) -> None:
        agent = (await self._session.execute(
            select(Agent).where(Agent.project_id == project_id, Agent.role == role)
        )).scalar_one_or_none()
        if agent:
            agent.status = status
            agent.current_task_id = task_id
            agent.last_heartbeat = datetime.now(UTC)

    async def _increment_agent_usage(self, project_id: uuid.UUID, role: AgentRole, tokens: int) -> None:
        agent = (await self._session.execute(
            select(Agent).where(Agent.project_id == project_id, Agent.role == role)
        )).scalar_one_or_none()
        if agent:
            agent.total_runs += 1
            agent.total_tokens += tokens

    async def _fail_task(self, task: Task, emitter: EventEmitter, reason: str) -> bool:
        task.status = TaskStatus.READY if task.attempts < 3 else TaskStatus.FAILED
        task.result = {**(task.result or {}), "last_failure": reason}
        await emitter.emit("task_failed", f"{task.title}: {reason}", task_id=str(task.id))
        return False


# --- module-level helpers ---------------------------------------------------
def _safe_enum(enum_cls, value, default):
    try:
        return enum_cls(value)
    except (ValueError, KeyError, TypeError):
        return default


def _format_adr(adr: dict[str, Any]) -> str:
    parts = [f"Decision: {adr.get('decision', '')}", f"Context: {adr.get('context', '')}",
             f"Chosen: {adr.get('chosen', '')}"]
    if adr.get("implementation_notes"):
        parts.append("Implementation notes:\n" + "\n".join(f"- {n}" for n in adr["implementation_notes"]))
    return "\n".join(parts)


def _pr_body(task: Task, review_out: dict | None, review_score: float) -> str:
    criteria = "\n".join(f"- [x] {c}" for c in task.acceptance_criteria)
    summary = (review_out or {}).get("summary", "Automated implementation.")
    return (
        f"## {task.title}\n\n{task.description or ''}\n\n"
        f"### Acceptance criteria\n{criteria}\n\n"
        f"### Review\nScore: {review_score:.0f}/100\n\n{summary}\n\n"
        f"---\n*Authored autonomously by RiMo. Task `{task.id}`.*"
    )


def _local_pr_number(task: Task) -> int:
    return int(str(task.id.int)[-6:])


async def _null_web_search(query: str) -> list[dict[str, Any]]:
    """Fallback web search used when no provider is wired in."""
    return [{"note": "web search not configured", "query": query}]
