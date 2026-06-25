"use client";

import { useState } from "react";
import {
  Brain,
  Check,
  GitMerge,
  RotateCcw,
  ShieldCheck,
  X,
} from "lucide-react";
import { Badge, Button, EmptyState, StatusDot } from "@/components/ui";
import { api } from "@/lib/api";
import type {
  Approval,
  Deployment,
  MemoryRecord,
  PullRequest,
  Task,
} from "@/types";
import {
  PRIORITY_LABEL,
  PRIORITY_TONE,
  relativeTime,
  roleColor,
  TASK_TONE,
} from "@/lib/utils";
import { ROLE_LABEL } from "@/types";

const TASK_COLUMNS: { key: Task["status"]; label: string }[] = [
  { key: "ready", label: "Ready" },
  { key: "in_progress", label: "In progress" },
  { key: "in_review", label: "In review" },
  { key: "done", label: "Done" },
];

export function TasksBoard({ tasks }: { tasks: Task[] }) {
  if (tasks.length === 0) {
    return (
      <EmptyState
        title="No tasks yet"
        hint="Run planning and the Planner agent will break the mission into a prioritized, dependency-ordered backlog."
      />
    );
  }

  const grouped = (status: Task["status"]) =>
    tasks
      .filter((t) => t.status === status)
      .sort((a, b) => a.priority - b.priority);

  const backlog = grouped("backlog");

  return (
    <div className="p-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        {TASK_COLUMNS.map((col) => {
          const items = grouped(col.key);
          return (
            <div key={col.key} className="flex flex-col gap-2.5">
              <div className="flex items-center justify-between px-1">
                <div className="flex items-center gap-2">
                  <StatusDot color={TASK_TONE[col.key]} size={6} />
                  <span className="text-xs font-semibold text-ink">{col.label}</span>
                </div>
                <span className="font-mono text-[0.6875rem] text-faint">{items.length}</span>
              </div>
              <div className="flex flex-col gap-2">
                {items.map((t) => (
                  <TaskCard key={t.id} task={t} />
                ))}
                {items.length === 0 && (
                  <div className="rounded-lg border border-dashed border-line/70 px-3 py-6 text-center font-mono text-[0.6875rem] text-faint">
                    empty
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {backlog.length > 0 && (
        <div className="mt-5 border-t border-line pt-4">
          <p className="mb-2.5 px-1 text-xs font-semibold text-muted">
            Backlog · {backlog.length}
          </p>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
            {backlog.slice(0, 12).map((t) => (
              <TaskCard key={t.id} task={t} muted />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TaskCard({ task, muted = false }: { task: Task; muted?: boolean }) {
  const color = roleColor(task.assigned_role);
  return (
    <div
      className={`rounded-lg border border-line bg-raised/40 p-3 ${muted ? "opacity-80" : ""}`}
    >
      <div className="flex items-start gap-2">
        <span
          className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ background: PRIORITY_TONE[task.priority] }}
          title={PRIORITY_LABEL[task.priority]}
        />
        <p className="text-sm leading-snug text-ink">{task.title}</p>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <Badge>{task.kind}</Badge>
        {task.assigned_role && (
          <span className="font-mono text-[0.625rem] uppercase" style={{ color }}>
            {ROLE_LABEL[task.assigned_role]}
          </span>
        )}
        <span className="ml-auto font-mono text-[0.625rem] text-faint">
          {task.complexity} pts
        </span>
      </div>
    </div>
  );
}

export function PullRequestList({ prs }: { prs: PullRequest[] }) {
  if (prs.length === 0) {
    return (
      <EmptyState
        title="No pull requests yet"
        hint="When the Builder finishes a task and the Reviewer, QA, and Security agents approve, RiMo opens a PR here."
      />
    );
  }
  const tone: Record<string, string> = {
    open: "#5B8CFF",
    approved: "#5FD17A",
    changes_requested: "#F2C14E",
    merged: "#8B7FF5",
    closed: "#6E7891",
  };
  return (
    <div className="divide-y divide-line">
      {prs.map((pr) => (
        <div key={pr.id} className="flex items-center gap-4 px-5 py-3.5">
          <GitMerge size={16} style={{ color: tone[pr.status] }} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-faint">#{pr.number}</span>
              <p className="truncate text-sm font-medium text-ink">{pr.title}</p>
            </div>
            <p className="mt-0.5 font-mono text-[0.6875rem] text-faint">
              <span className="text-ok">+{pr.additions}</span>{" "}
              <span className="text-danger">−{pr.deletions}</span> · {pr.files_changed} files ·{" "}
              {pr.head_branch} → {pr.base_branch}
            </p>
          </div>
          {pr.review_score != null && (
            <div className="text-right">
              <p
                className="font-mono text-sm font-semibold tabular-nums"
                style={{ color: pr.review_score >= 80 ? "#5FD17A" : "#F2C14E" }}
              >
                {Math.round(pr.review_score)}
              </p>
              <p className="font-mono text-[0.625rem] text-faint">review</p>
            </div>
          )}
          <div className="flex items-center gap-2">
            {pr.checks_passing ? (
              <Badge color="#5FD17A">
                <Check size={11} /> checks
              </Badge>
            ) : (
              <Badge color="#F2C14E">pending</Badge>
            )}
            <Badge color={tone[pr.status]}>{pr.status.replace("_", " ")}</Badge>
          </div>
        </div>
      ))}
    </div>
  );
}

export function DeploymentList({
  deployments,
  onChange,
}: {
  deployments: Deployment[];
  onChange: () => void;
}) {
  if (deployments.length === 0) {
    return (
      <EmptyState
        title="No deployments yet"
        hint="Once a PR merges, the DevOps agent ships it (subject to approval) and records the deployment here."
      />
    );
  }
  const tone: Record<string, string> = {
    queued: "#6E7891",
    running: "#5B8CFF",
    succeeded: "#5FD17A",
    failed: "#E5544B",
    rolled_back: "#F2C14E",
  };
  return (
    <div className="divide-y divide-line">
      {deployments.map((d) => (
        <div key={d.id} className="flex items-center gap-4 px-5 py-3.5">
          <StatusDot color={tone[d.status]} pulse={d.status === "running"} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium text-ink">{d.environment}</p>
              <span className="font-mono text-[0.6875rem] text-faint">
                {d.commit_sha?.slice(0, 7) ?? "—"}
              </span>
            </div>
            <p className="mt-0.5 font-mono text-[0.6875rem] text-faint">
              {relativeTime(d.created_at)}
              {d.duration_seconds != null ? ` · ${d.duration_seconds.toFixed(1)}s` : ""}
            </p>
          </div>
          {d.url && (
            <a
              href={d.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-xs text-signal hover:underline"
            >
              open
            </a>
          )}
          <Badge color={tone[d.status]}>{d.status.replace("_", " ")}</Badge>
          {d.status === "succeeded" && (
            <Button
              variant="ghost"
              className="px-2 py-1 text-xs"
              onClick={async () => {
                await api.rollback(d.id);
                onChange();
              }}
            >
              <RotateCcw size={13} /> roll back
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}

export function MemoryList({ memory }: { memory: MemoryRecord[] }) {
  if (memory.length === 0) {
    return (
      <EmptyState
        icon={<Brain size={26} />}
        title="No memories yet"
        hint="As the company completes work, the Memory agent distills durable lessons — architecture decisions, bug fixes, and patterns that worked — for future recall."
      />
    );
  }
  const kindTone: Record<string, string> = {
    architecture_decision: "#4EC3C1",
    bug_fix: "#E5544B",
    user_preference: "#F2C14E",
    project_fact: "#5B8CFF",
    successful_implementation: "#5FD17A",
    lesson_learned: "#8B7FF5",
  };
  return (
    <div className="divide-y divide-line">
      {memory.map((m) => (
        <div key={m.id} className="px-5 py-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-ink">{m.title}</p>
            <Badge color={kindTone[m.kind] ?? "#6E7891"}>
              {m.kind.replace(/_/g, " ")}
            </Badge>
          </div>
          <p className="mt-1.5 text-sm leading-relaxed text-muted">{m.content}</p>
          <div className="mt-2 flex items-center gap-3 font-mono text-[0.625rem] text-faint">
            <span>importance {(m.importance * 100).toFixed(0)}%</span>
            <span>recalled {m.access_count}×</span>
            <span>{relativeTime(m.created_at)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ApprovalQueue({
  approvals,
  onDecide,
}: {
  approvals: Approval[];
  onDecide: () => void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const pending = approvals.filter((a) => a.approved === null);

  if (pending.length === 0) {
    return (
      <EmptyState
        icon={<ShieldCheck size={26} />}
        title="Nothing awaiting approval"
        hint="High-risk actions — merging PRs, deploying, destructive migrations — pause here for your sign-off."
      />
    );
  }

  async function decide(id: string, approved: boolean) {
    setBusyId(id);
    try {
      await api.decideApproval(id, approved);
      onDecide();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="divide-y divide-line">
      {pending.map((a) => (
        <div key={a.id} className="flex items-center gap-4 px-5 py-4">
          <div
            className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-warn/15 text-warn"
          >
            <ShieldCheck size={17} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <Badge color="#F2C14E">{a.kind.replace(/_/g, " ")}</Badge>
              <span className="font-mono text-[0.625rem] text-faint">
                {relativeTime(a.created_at)}
              </span>
            </div>
            <p className="mt-1.5 text-sm text-ink">{a.summary}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="danger"
              className="px-3 py-1.5 text-xs"
              disabled={busyId === a.id}
              onClick={() => decide(a.id, false)}
            >
              <X size={13} /> Reject
            </Button>
            <Button
              variant="primary"
              className="px-3 py-1.5 text-xs"
              disabled={busyId === a.id}
              onClick={() => decide(a.id, true)}
            >
              <Check size={13} /> Approve
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
