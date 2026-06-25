"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Boxes,
  GitMerge,
  GitPullRequest,
  Rocket,
  ShieldAlert,
  Users,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { AgentFloor } from "@/components/agent-floor";
import { Badge, Button, EmptyState, Eyebrow, Panel, PanelHeader, Stat, StatusDot } from "@/components/ui";
import { useAuth, usePolling } from "@/hooks";
import { api } from "@/lib/api";
import type { AgentView, DashboardSummary, Project } from "@/types";
import { relativeTime } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  active: "#5FD17A",
  analyzing: "#5B8CFF",
  paused: "#F2C14E",
  blocked: "#E5544B",
  draft: "#6E7891",
  archived: "#454C61",
};

export default function OperationsPage() {
  const { user, ready } = useAuth();
  const { data: summary } = usePolling<DashboardSummary>(() => api.dashboard(), 5000);
  const { data: projects } = usePolling<Project[]>(() => api.projects(), 8000);

  // Aggregate the agent floor across the most active running project (or first).
  const activeProject = projects?.find((p) => p.is_running) ?? projects?.[0];
  const { data: agents } = usePolling<AgentView[]>(
    () => (activeProject ? api.agents(activeProject.id) : Promise.resolve([])),
    4000,
    [activeProject?.id],
  );

  if (!ready) return null;

  return (
    <AppShell user={user}>
      <header className="mb-7 flex items-end justify-between">
        <div>
          <Eyebrow>Operations Console</Eyebrow>
          <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">
            The company is shipping.
          </h1>
          <p className="mt-1 text-sm text-muted">
            Ten specialist agents planning, building, reviewing, and deploying across your projects.
          </p>
        </div>
        <Link href="/projects">
          <Button variant="primary">
            <Boxes size={15} />
            New project
          </Button>
        </Link>
      </header>

      {/* Ops bar */}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <OpsCard icon={<Boxes size={15} />} label="Active projects" value={summary?.projects_active} tone="#5B8CFF" />
        <OpsCard icon={<Users size={15} />} label="Agents running" value={summary?.agents_running} tone="#5FD17A" />
        <OpsCard icon={<GitPullRequest size={15} />} label="Tasks queued" value={summary?.tasks_queued} tone="#F08A5D" />
        <OpsCard icon={<GitMerge size={15} />} label="Open PRs" value={summary?.prs_open} tone="#8B7FF5" />
        <OpsCard icon={<Rocket size={15} />} label="Deploys today" value={summary?.deployments_today} tone="#3FB4E8" />
        <OpsCard
          icon={<ShieldAlert size={15} />}
          label="Approvals"
          value={summary?.pending_approvals}
          tone={summary && summary.pending_approvals > 0 ? "#E5544B" : "#6E7891"}
          alert={!!summary && summary.pending_approvals > 0}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.5fr_1fr]">
        {/* Agent floor */}
        <Panel>
          <PanelHeader
            title="The Floor"
            hint={activeProject ? activeProject.name : "no active project"}
            action={
              <Link
                href="/agents"
                className="flex items-center gap-1 font-mono text-xs text-muted transition-colors hover:text-ink"
              >
                full view <ArrowUpRight size={13} />
              </Link>
            }
          />
          <div className="p-4">
            <AgentFloor agents={agents ?? []} />
          </div>
        </Panel>

        {/* Projects */}
        <Panel>
          <PanelHeader title="Projects" hint={`${projects?.length ?? 0} total`} />
          <div className="divide-y divide-line">
            {!projects || projects.length === 0 ? (
              <EmptyState
                icon={<Boxes size={26} />}
                title="No projects yet"
                hint="Connect a GitHub repo or describe an idea, and RiMo's CEO agent will set the mission."
                action={
                  <Link href="/projects">
                    <Button variant="primary">Create the first project</Button>
                  </Link>
                }
              />
            ) : (
              projects.slice(0, 7).map((p) => (
                <Link
                  key={p.id}
                  href={`/projects/${p.id}`}
                  className="flex items-center gap-3 px-5 py-3.5 transition-colors hover:bg-raised/40"
                >
                  <StatusDot
                    color={STATUS_TONE[p.status] ?? "#6E7891"}
                    pulse={p.is_running}
                    size={7}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{p.name}</p>
                    <p className="truncate font-mono text-[0.6875rem] text-faint">
                      {p.repo_full_name ?? "greenfield"} · {relativeTime(p.updated_at)}
                    </p>
                  </div>
                  <Badge color={STATUS_TONE[p.status]}>{p.status}</Badge>
                </Link>
              ))
            )}
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}

function OpsCard({
  icon,
  label,
  value,
  tone,
  alert = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | undefined;
  tone: string;
  alert?: boolean;
}) {
  return (
    <Panel className="relative overflow-hidden p-4">
      {alert && (
        <span className="absolute right-3 top-3 h-2 w-2 animate-breathe rounded-full bg-danger" />
      )}
      <div className="mb-3 inline-flex rounded-[9px] p-1.5" style={{ background: `${tone}18`, color: tone }}>
        {icon}
      </div>
      <Stat label={label} value={value ?? "—"} accent={tone} />
    </Panel>
  );
}
