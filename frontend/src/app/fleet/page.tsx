"use client";

import Link from "next/link";
import { AlertTriangle, Boxes, GitBranch, Layers, ShieldAlert } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Eyebrow, Panel, PanelHeader, Stat, StatusDot } from "@/components/ui";
import { useAuth, usePolling } from "@/hooks";
import { api } from "@/lib/api";
import type { FleetView } from "@/types";

const STATUS_TONE: Record<string, string> = {
  active: "#5FD17A",
  analyzing: "#5B8CFF",
  paused: "#F2C14E",
  blocked: "#E5544B",
  draft: "#6E7891",
  archived: "#454C61",
};

function attentionTone(score: number): string {
  if (score >= 1.0) return "#E5544B";
  if (score >= 0.5) return "#F2C14E";
  if (score >= 0.2) return "#5B8CFF";
  return "#6E7891";
}

export default function FleetPage() {
  const { user, ready } = useAuth();
  const { data: fleet } = usePolling<FleetView>(() => api.fleet(), 6000);

  if (!ready) return null;

  return (
    <AppShell user={user}>
      <header className="mb-7">
        <Eyebrow>RiMo OS</Eyebrow>
        <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">Fleet</h1>
        <p className="mt-1 text-sm text-muted">
          One operating system over the whole portfolio. Projects are ranked by how much they need
          attention — pending approvals and blockers rise to the top.
        </p>
      </header>

      {/* Fleet-wide stats */}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Panel className="p-4">
          <div className="mb-3 inline-flex rounded-[9px] bg-signal/15 p-1.5 text-signal">
            <Layers size={15} />
          </div>
          <Stat label="Projects" value={fleet?.total_projects ?? "—"} accent="#5B8CFF" />
        </Panel>
        <Panel className="p-4">
          <div className="mb-3 inline-flex rounded-[9px] bg-ok/15 p-1.5 text-ok">
            <GitBranch size={15} />
          </div>
          <Stat label="Running" value={fleet?.running ?? "—"} accent="#5FD17A" />
        </Panel>
        <Panel className="p-4">
          <div className="mb-3 inline-flex rounded-[9px] bg-danger/15 p-1.5 text-danger">
            <AlertTriangle size={15} />
          </div>
          <Stat label="Blocked" value={fleet?.blocked ?? "—"} accent="#E5544B" />
        </Panel>
        <Panel className="p-4">
          <div className="mb-3 inline-flex rounded-[9px] bg-role-builder/15 p-1.5 text-role-builder">
            <Boxes size={15} />
          </div>
          <Stat label="Open tasks" value={fleet?.total_open_tasks ?? "—"} accent="#F08A5D" />
        </Panel>
        <Panel className="relative p-4">
          {!!fleet && fleet.total_pending_approvals > 0 && (
            <span className="absolute right-3 top-3 h-2 w-2 animate-breathe rounded-full bg-danger" />
          )}
          <div className="mb-3 inline-flex rounded-[9px] bg-warn/15 p-1.5 text-warn">
            <ShieldAlert size={15} />
          </div>
          <Stat
            label="Approvals"
            value={fleet?.total_pending_approvals ?? "—"}
            accent={fleet && fleet.total_pending_approvals > 0 ? "#E5544B" : "#6E7891"}
          />
        </Panel>
      </div>

      {/* Attention-ranked project list */}
      <Panel>
        <PanelHeader title="Attention queue" hint="highest priority first" />
        <div className="divide-y divide-line">
          {!fleet || fleet.projects.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm text-muted">
              No projects in the fleet yet.
            </div>
          ) : (
            fleet.projects.map((p) => (
              <Link
                key={p.project_id}
                href={`/projects/${p.project_id}`}
                className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-raised/40"
              >
                {/* attention meter */}
                <div className="flex w-12 shrink-0 flex-col items-center">
                  <span
                    className="font-mono text-sm font-semibold tabular-nums"
                    style={{ color: attentionTone(p.attention_score) }}
                  >
                    {p.attention_score.toFixed(1)}
                  </span>
                  <div className="mt-1 h-1 w-full overflow-hidden rounded-pill bg-raised">
                    <div
                      className="h-full rounded-pill"
                      style={{
                        width: `${Math.min(100, p.attention_score * 50)}%`,
                        background: attentionTone(p.attention_score),
                      }}
                    />
                  </div>
                </div>

                <StatusDot color={STATUS_TONE[p.status] ?? "#6E7891"} pulse={p.is_running} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">{p.name}</p>
                  <p className="font-mono text-[0.6875rem] text-faint">
                    {p.open_tasks} open · {p.pending_approvals} awaiting approval
                  </p>
                </div>
                {p.pending_approvals > 0 && <Badge color="#E5544B">needs approval</Badge>}
                <Badge color={STATUS_TONE[p.status]}>{p.status}</Badge>
              </Link>
            ))
          )}
        </div>
      </Panel>
    </AppShell>
  );
}
