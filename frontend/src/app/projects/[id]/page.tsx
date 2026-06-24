"use client";

import { use, useState } from "react";
import Link from "next/link";
import {
  ChevronLeft,
  Github,
  ListTodo,
  Pause,
  Play,
  Sparkles,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { AgentFloor } from "@/components/agent-floor";
import { ActivityTimeline } from "@/components/activity-timeline";
import {
  ApprovalQueue,
  DeploymentList,
  MemoryList,
  PullRequestList,
  TasksBoard,
} from "@/components/project-tabs";
import {
  EconomicsPanel,
  GraphPanel,
  IncidentsPanel,
  MarketplacePanel,
  SmellsPanel,
} from "@/components/intelligence";
import { Badge, Button, Eyebrow, Panel, PanelHeader, Stat } from "@/components/ui";
import { useActivityStream, useAuth, usePolling } from "@/hooks";
import { api } from "@/lib/api";
import type {
  ActivityEvent,
  AgentView,
  Approval,
  CentralNode,
  CostSummary,
  Deployment,
  GraphData,
  Incident,
  MarketplaceAgent,
  MemoryRecord,
  Project,
  ProjectMetrics,
  PullRequest,
  Smell,
  Task,
} from "@/types";

const STATUS_TONE: Record<string, string> = {
  active: "#5FD17A",
  analyzing: "#5B8CFF",
  paused: "#F2C14E",
  blocked: "#E5544B",
  draft: "#6E7891",
  archived: "#454C61",
};

type Tab =
  | "tasks"
  | "prs"
  | "deploys"
  | "memory"
  | "approvals"
  | "economics"
  | "graph"
  | "incidents"
  | "health";

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user, ready } = useAuth();
  const [tab, setTab] = useState<Tab>("tasks");
  const [busy, setBusy] = useState(false);

  const { data: project, refetch: refetchProject } = usePolling<Project>(
    () => api.project(id),
    6000,
    [id],
  );
  const { data: agents } = usePolling<AgentView[]>(() => api.agents(id), 4000, [id]);
  const { data: metrics } = usePolling<ProjectMetrics>(() => api.metrics(id), 6000, [id]);
  const { data: tasks, refetch: refetchTasks } = usePolling<Task[]>(
    () => api.tasks(id),
    6000,
    [id],
  );
  const { data: prs } = usePolling<PullRequest[]>(() => api.prs(id), 6000, [id]);
  const { data: deploys, refetch: refetchDeploys } = usePolling<Deployment[]>(
    () => api.deployments(id),
    6000,
    [id],
  );
  const { data: memory } = usePolling<MemoryRecord[]>(() => api.memory(id), 10000, [id]);
  const { data: approvals, refetch: refetchApprovals } = usePolling<Approval[]>(
    () => api.approvals(id),
    5000,
    [id],
  );
  const { data: seed } = usePolling<ActivityEvent[]>(() => api.activity(id, 60), 60000, [id]);
  const { events, connected } = useActivityStream(id, seed ?? []);

  // Intelligence layer
  const { data: economics } = usePolling<CostSummary>(() => api.economics(id), 8000, [id]);
  const { data: graphStats } = usePolling<GraphData>(() => api.graph(id), 30000, [id]);
  const { data: central } = usePolling<CentralNode[]>(() => api.centralNodes(id), 30000, [id]);
  const { data: incidents } = usePolling<Incident[]>(() => api.incidents(id), 8000, [id]);
  const { data: smells } = usePolling<Smell[]>(() => api.smells(id), 30000, [id]);
  const { data: recommendedAgents } = usePolling<MarketplaceAgent[]>(
    () => api.recommendedAgents(id),
    60000,
    [id],
  );
  const { data: allAgents } = usePolling<MarketplaceAgent[]>(() => api.marketplace(), 120000);

  if (!ready) return null;

  const pendingApprovals = (approvals ?? []).filter((a) => a.approved === null).length;

  async function toggleRun() {
    if (!project) return;
    setBusy(true);
    try {
      if (project.is_running) await api.pauseProject(id);
      else await api.startProject(id);
      await refetchProject();
    } finally {
      setBusy(false);
    }
  }

  async function plan() {
    setBusy(true);
    try {
      await api.planProject(id);
      await refetchTasks();
    } finally {
      setBusy(false);
    }
  }

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "tasks", label: "Tasks", count: tasks?.length },
    { key: "prs", label: "Pull requests", count: prs?.length },
    { key: "deploys", label: "Deployments", count: deploys?.length },
    { key: "graph", label: "Knowledge graph", count: graphStats?.stats.nodes },
    { key: "economics", label: "Economics" },
    { key: "incidents", label: "Incidents", count: incidents?.length || undefined },
    { key: "health", label: "Architecture", count: smells?.length || undefined },
    { key: "memory", label: "Memory", count: memory?.length },
    { key: "approvals", label: "Approvals", count: pendingApprovals || undefined },
  ];

  return (
    <AppShell user={user}>
      <Link
        href="/projects"
        className="mb-4 inline-flex items-center gap-1 font-mono text-xs text-muted transition-colors hover:text-ink"
      >
        <ChevronLeft size={14} /> Projects
      </Link>

      {/* Header + controls */}
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">
              {project?.name ?? "…"}
            </h1>
            {project && (
              <Badge color={STATUS_TONE[project.status]}>{project.status}</Badge>
            )}
          </div>
          <p className="mt-1.5 max-w-2xl text-sm text-muted">
            {project?.mission ?? project?.description ?? "Mission not yet set."}
          </p>
          {project?.repo_full_name && (
            <a
              href={project.repo_url ?? "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1.5 font-mono text-xs text-faint hover:text-muted"
            >
              <Github size={12} /> {project.repo_full_name}
            </a>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Button variant="default" onClick={plan} disabled={busy}>
            <Sparkles size={15} /> Plan
          </Button>
          <Button variant={project?.is_running ? "danger" : "primary"} onClick={toggleRun} disabled={busy}>
            {project?.is_running ? (
              <>
                <Pause size={15} /> Pause
              </>
            ) : (
              <>
                <Play size={15} /> Start company
              </>
            )}
          </Button>
        </div>
      </header>

      {/* Metrics strip */}
      <Panel className="mb-6 grid grid-cols-2 gap-6 p-5 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Tasks done" value={`${metrics?.tasks_done ?? 0}/${metrics?.tasks_total ?? 0}`} />
        <Stat label="In progress" value={metrics?.tasks_in_progress ?? 0} accent="#5FD17A" />
        <Stat label="Open PRs" value={metrics?.open_prs ?? 0} accent="#8B7FF5" />
        <Stat label="Merged PRs" value={metrics?.merged_prs ?? 0} accent="#5B8CFF" />
        <Stat label="Velocity 7d" value={(metrics?.velocity_7d ?? 0).toFixed(1)} accent="#F08A5D" sub="pts/day" />
        <Stat
          label="Avg review"
          value={metrics?.avg_review_score != null ? Math.round(metrics.avg_review_score) : "—"}
          accent="#4EC3C1"
        />
      </Panel>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.6fr_1fr]">
        <div className="space-y-6">
          {/* Agent floor (compact) */}
          <Panel>
            <PanelHeader title="The Floor" hint={`${agents?.length ?? 0} agents`} />
            <div className="p-4">
              <AgentFloor agents={agents ?? []} compact />
            </div>
          </Panel>

          {/* Tabbed work surface */}
          <Panel>
            <div className="flex items-center gap-1 overflow-x-auto border-b border-line px-3">
              {tabs.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`relative whitespace-nowrap px-3.5 py-3 text-sm transition-colors ${
                    tab === t.key ? "text-ink" : "text-muted hover:text-ink"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    {t.label}
                    {t.count != null && (
                      <span
                        className={`rounded-pill px-1.5 py-0.5 font-mono text-[0.625rem] ${
                          t.key === "approvals" && t.count > 0
                            ? "bg-danger/20 text-danger"
                            : "bg-raised text-faint"
                        }`}
                      >
                        {t.count}
                      </span>
                    )}
                  </span>
                  {tab === t.key && (
                    <span className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-signal" />
                  )}
                </button>
              ))}
            </div>

            {tab === "tasks" && <TasksBoard tasks={tasks ?? []} />}
            {tab === "prs" && <PullRequestList prs={prs ?? []} />}
            {tab === "deploys" && (
              <DeploymentList deployments={deploys ?? []} onChange={refetchDeploys} />
            )}
            {tab === "graph" && (
              <GraphPanel stats={graphStats?.stats ?? null} central={central ?? null} />
            )}
            {tab === "economics" && <EconomicsPanel data={economics ?? null} />}
            {tab === "incidents" && <IncidentsPanel incidents={incidents ?? null} />}
            {tab === "health" && (
              <div className="divide-y divide-line">
                <SmellsPanel smells={smells ?? null} />
                <MarketplacePanel recommended={recommendedAgents ?? null} all={allAgents ?? null} />
              </div>
            )}
            {tab === "memory" && <MemoryList memory={memory ?? []} />}
            {tab === "approvals" && (
              <ApprovalQueue approvals={approvals ?? []} onDecide={refetchApprovals} />
            )}
          </Panel>
        </div>

        {/* Live activity stream */}
        <Panel className="sticky top-6 h-[calc(100vh-3rem)] overflow-hidden">
          <ActivityTimeline events={events} connected={connected} />
        </Panel>
      </div>
    </AppShell>
  );
}

export { ListTodo, Eyebrow };
