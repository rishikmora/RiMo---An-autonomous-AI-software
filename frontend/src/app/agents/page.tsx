"use client";

import { AppShell } from "@/components/app-shell";
import { AgentFloor } from "@/components/agent-floor";
import { Eyebrow, Panel, PanelHeader } from "@/components/ui";
import { useAuth, usePolling } from "@/hooks";
import { api } from "@/lib/api";
import type { AgentView, Project } from "@/types";

export default function FloorPage() {
  const { user, ready } = useAuth();
  const { data: projects } = usePolling<Project[]>(() => api.projects(), 8000);

  if (!ready) return null;
  const running = (projects ?? []).filter((p) => p.is_running);
  const shown = running.length > 0 ? running : (projects ?? []).slice(0, 1);

  return (
    <AppShell user={user}>
      <header className="mb-7">
        <Eyebrow>Company Floor</Eyebrow>
        <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">
          Every agent, every project
        </h1>
        <p className="mt-1 text-sm text-muted">
          Each running project staffs a full company of ten specialists. Live status updates every
          few seconds.
        </p>
      </header>

      {shown.length === 0 ? (
        <Panel className="p-10 text-center text-sm text-muted">
          No active projects. Start one to see its company come online.
        </Panel>
      ) : (
        <div className="space-y-6">
          {shown.map((p) => (
            <ProjectFloor key={p.id} project={p} />
          ))}
        </div>
      )}
    </AppShell>
  );
}

function ProjectFloor({ project }: { project: Project }) {
  const { data: agents } = usePolling<AgentView[]>(() => api.agents(project.id), 4000, [project.id]);
  return (
    <Panel>
      <PanelHeader
        title={project.name}
        hint={project.repo_full_name ?? "greenfield"}
        action={
          <span className="font-mono text-xs text-faint">
            {project.is_running ? "running" : "idle"}
          </span>
        }
      />
      <div className="p-4">
        <AgentFloor agents={agents ?? []} />
      </div>
    </Panel>
  );
}
