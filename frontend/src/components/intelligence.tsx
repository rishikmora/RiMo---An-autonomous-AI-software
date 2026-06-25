"use client";

import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  CircleDollarSign,
  GitBranch,
  Sparkles,
  TrendingDown,
} from "lucide-react";
import type {
  CentralNode,
  CostSummary,
  Incident,
  MarketplaceAgent,
  PromptVariantStat,
  Smell,
  SpendData,
} from "@/types";
import { Badge, EmptyState, Eyebrow, StatusDot } from "@/components/ui";
import { compactNumber, relativeTime } from "@/lib/utils";

const NODE_TONE: Record<string, string> = {
  module: "#A0A6B8",
  file: "#5B8CFF",
  class: "#8B7FF5",
  function: "#5FD17A",
  api_route: "#F08A5D",
  db_table: "#4EC3C1",
  service: "#3FB4E8",
  external: "#6E7891",
};

function usd(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 0.01 && n > 0) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

// --- Economics: the company's unit economics + routing savings ---
export function EconomicsPanel({ data }: { data: CostSummary | null }) {
  if (!data) {
    return <EmptyState icon={<CircleDollarSign size={26} />} title="No spend recorded yet" hint="Once agents run, every model call's cost is logged here." />;
  }
  const models = Object.entries(data.by_model).sort((a, b) => b[1] - a[1]);
  const maxModel = models[0]?.[1] ?? 1;

  return (
    <div className="p-5">
      <div className="grid grid-cols-2 gap-5 md:grid-cols-4">
        <Figure label="Total spend" value={usd(data.total_usd)} accent="#5FD17A" />
        <Figure label="Model calls" value={compactNumber(data.calls)} />
        <Figure label="Per merged PR" value={usd(data.cost_per_merged_pr)} accent="#8B7FF5" />
        <Figure label="Per task" value={usd(data.cost_per_completed_task)} accent="#5B8CFF" />
      </div>

      {/* Routing savings — the headline number for multi-model routing */}
      <div className="mt-5 rounded-card border border-ok/25 bg-ok/5 p-4">
        <div className="flex items-center gap-2">
          <TrendingDown size={16} className="text-ok" />
          <Eyebrow className="text-ok">Routing efficiency</Eyebrow>
        </div>
        <div className="mt-2 flex items-end justify-between">
          <div>
            <p className="font-mono text-2xl font-semibold text-ok">
              {data.routing_savings_pct.toFixed(0)}% saved
            </p>
            <p className="mt-0.5 text-sm text-muted">
              {usd(data.routing_savings_usd)} vs {usd(data.naive_baseline_usd)} frontier-only baseline
            </p>
          </div>
          <Badge color="#5FD17A">multi-model routing</Badge>
        </div>
      </div>

      {/* Spend by model */}
      {models.length > 0 && (
        <div className="mt-5">
          <Eyebrow>Spend by model</Eyebrow>
          <div className="mt-2.5 space-y-2">
            {models.map(([model, cost]) => (
              <div key={model} className="flex items-center gap-3">
                <span className="w-48 shrink-0 truncate font-mono text-xs text-muted">{model}</span>
                <div className="h-2 flex-1 overflow-hidden rounded-pill bg-raised">
                  <div
                    className="h-full rounded-pill bg-signal"
                    style={{ width: `${Math.max(3, (cost / maxModel) * 100)}%` }}
                  />
                </div>
                <span className="w-16 shrink-0 text-right font-mono text-xs text-ink">{usd(cost)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Figure({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <Eyebrow>{label}</Eyebrow>
      <span className="font-mono text-xl font-semibold tabular-nums" style={{ color: accent ?? "#E8EAF0" }}>
        {value}
      </span>
    </div>
  );
}

// --- Knowledge graph: structural brain summary ---
export function GraphPanel({
  stats,
  central,
}: {
  stats: { nodes: number; edges: number } | null;
  central: CentralNode[] | null;
}) {
  if (!stats || stats.nodes === 0) {
    return (
      <EmptyState
        icon={<GitBranch size={26} />}
        title="Knowledge graph not built yet"
        hint="When RiMo analyzes the codebase, it maps every file, class, function, route, and table into a queryable graph — its structural brain."
      />
    );
  }
  return (
    <div className="p-5">
      <div className="flex items-center gap-6">
        <Figure label="Nodes" value={compactNumber(stats.nodes)} accent="#5B8CFF" />
        <Figure label="Edges" value={compactNumber(stats.edges)} accent="#8B7FF5" />
        <div className="ml-auto">
          <Badge color="#4EC3C1">PageRank centrality</Badge>
        </div>
      </div>

      <div className="mt-5">
        <Eyebrow>Most load-bearing nodes</Eyebrow>
        <p className="mb-3 mt-1 text-xs text-muted">
          Highest blast radius — changing these affects the most other code.
        </p>
        <div className="space-y-1.5">
          {(central ?? []).slice(0, 10).map((n, i) => (
            <div key={`${n.path}-${n.name}-${i}`} className="flex items-center gap-3 rounded-lg border border-line bg-raised/30 px-3 py-2">
              <span className="w-5 text-center font-mono text-xs text-faint">{i + 1}</span>
              <StatusDot color={NODE_TONE[n.kind] ?? "#6E7891"} size={7} />
              <span className="text-sm font-medium text-ink">{n.name}</span>
              <Badge color={NODE_TONE[n.kind]}>{n.kind.replace("_", " ")}</Badge>
              {n.path && (
                <span className="ml-auto truncate font-mono text-[0.625rem] text-faint">{n.path}</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// --- Incidents: autonomous failure recovery ---
const INCIDENT_TONE: Record<string, string> = {
  open: "#6E7891",
  diagnosing: "#5B8CFF",
  recovered: "#5FD17A",
  rolled_back: "#F2C14E",
  escalated: "#E5544B",
};

export function IncidentsPanel({ incidents }: { incidents: Incident[] | null }) {
  if (!incidents || incidents.length === 0) {
    return (
      <EmptyState
        icon={<CheckCircle2 size={26} />}
        title="No incidents"
        hint="When a build, test, or deploy fails, RiMo opens an incident here and runs diagnose → retry → rollback → escalate autonomously."
      />
    );
  }
  return (
    <div className="divide-y divide-line">
      {incidents.map((inc) => (
        <div key={inc.id} className="px-5 py-4">
          <div className="flex items-center gap-3">
            {inc.status === "escalated" ? (
              <AlertTriangle size={16} className="text-danger" />
            ) : (
              <StatusDot color={INCIDENT_TONE[inc.status]} pulse={inc.status === "diagnosing"} />
            )}
            <p className="flex-1 text-sm font-medium text-ink">{inc.title}</p>
            <Badge color={INCIDENT_TONE[inc.status]}>{inc.status.replace("_", " ")}</Badge>
          </div>
          <div className="mt-1.5 flex items-center gap-3 pl-7 font-mono text-[0.625rem] text-faint">
            <span>trigger: {inc.trigger}</span>
            <span>{inc.attempts} attempts</span>
            <span>{relativeTime(inc.created_at)}</span>
          </div>
          {inc.diagnosis && (
            <p className="mt-2 pl-7 text-xs leading-relaxed text-muted">{inc.diagnosis}</p>
          )}
          {inc.resolution && (
            <p className="mt-1 pl-7 text-xs text-ok">→ {inc.resolution}</p>
          )}
        </div>
      ))}
    </div>
  );
}

// --- Live spend ticker ---
export function SpendTicker({ spend }: { spend: SpendData | null }) {
  if (!spend) return null;
  return (
    <div className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <Eyebrow>Recent model calls</Eyebrow>
        <span className="font-mono text-sm font-semibold text-ok">{usd(spend.total_usd)} total</span>
      </div>
      <div className="space-y-1">
        {spend.recent_calls.map((c, i) => (
          <div key={i} className="flex items-center gap-2 font-mono text-[0.6875rem]">
            <Sparkles size={11} className="text-signal" />
            <span className="text-muted">{c.model}</span>
            <span className="text-faint">·</span>
            <span className="text-faint">{compactNumber(c.tokens)} tok</span>
            {c.purpose && <Badge>{c.purpose}</Badge>}
            <span className="ml-auto text-ink">{usd(c.cost_usd)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Prompt leaderboard: self-evolving prompts ---
export function PromptLeaderboard({ variants }: { variants: PromptVariantStat[] | null }) {
  if (!variants || variants.length === 0) {
    return <EmptyState icon={<Brain size={26} />} title="No prompt variants yet" hint="As agents run, RiMo tracks prompt performance and evolves better variants over time." />;
  }
  return (
    <div className="divide-y divide-line">
      {variants.map((v, i) => (
        <div key={v.name} className="flex items-center gap-3 px-5 py-3">
          <span className="w-5 text-center font-mono text-xs text-faint">{i + 1}</span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm text-ink">{v.name}</span>
              {v.generation > 0 && <Badge color="#8B7FF5">gen {v.generation}</Badge>}
              {!v.active && <Badge>retired</Badge>}
            </div>
            <p className="mt-0.5 font-mono text-[0.625rem] text-faint">
              {v.successes}/{v.trials} trials · reward {v.mean_reward.toFixed(2)}
            </p>
          </div>
          <span
            className="font-mono text-sm font-semibold tabular-nums"
            style={{ color: v.success_rate >= 0.7 ? "#5FD17A" : v.success_rate >= 0.4 ? "#F2C14E" : "#E5544B" }}
          >
            {(v.success_rate * 100).toFixed(0)}%
          </span>
        </div>
      ))}
    </div>
  );
}

// --- Architecture smells: refactor opportunities ---
const SMELL_TONE: Record<string, string> = {
  god_object: "#E5544B",
  hub_file: "#F2C14E",
  cycle: "#E36AA8",
  deep_chain: "#F08A5D",
};

export function SmellsPanel({ smells }: { smells: Smell[] | null }) {
  if (!smells || smells.length === 0) {
    return (
      <EmptyState
        icon={<GitBranch size={26} />}
        title="No architectural smells detected"
        hint="RiMo scans the knowledge graph for God objects, hub files, circular dependencies, and deep chains — then proposes scoped refactors."
      />
    );
  }
  return (
    <div className="divide-y divide-line">
      {smells.map((s, i) => (
        <div key={`${s.kind}-${i}`} className="px-5 py-4">
          <div className="flex items-center gap-3">
            <StatusDot color={SMELL_TONE[s.kind] ?? "#6E7891"} size={8} />
            <span className="text-sm font-medium text-ink">{s.node_name}</span>
            <Badge color={SMELL_TONE[s.kind]}>{s.kind.replace(/_/g, " ")}</Badge>
            <span
              className="ml-auto font-mono text-xs font-semibold"
              style={{ color: s.severity >= 0.8 ? "#E5544B" : "#F2C14E" }}
            >
              {(s.severity * 100).toFixed(0)}%
            </span>
          </div>
          <p className="mt-1.5 pl-7 font-mono text-[0.625rem] text-faint">{s.metric}</p>
          <p className="mt-1 pl-7 text-xs text-muted">{s.suggestion}</p>
        </div>
      ))}
    </div>
  );
}

// --- Agent marketplace: hireable specialists ---
const SPECIALIST_GLYPH: Record<string, string> = {
  flutter: "◆",
  ml: "❖",
  nextjs: "▣",
  data: "▦",
  "mobile-rn": "◇",
};

export function MarketplacePanel({
  recommended,
  all,
}: {
  recommended: MarketplaceAgent[] | null;
  all: MarketplaceAgent[] | null;
}) {
  const recSlugs = new Set((recommended ?? []).map((a) => a.slug));
  const catalog = all ?? [];
  return (
    <div className="p-5">
      <Eyebrow>Recommended for this project</Eyebrow>
      <p className="mb-3 mt-1 text-xs text-muted">
        Matched automatically from the project&apos;s detected stack.
      </p>
      {(recommended ?? []).length === 0 ? (
        <p className="rounded-lg border border-dashed border-line/70 px-3 py-4 text-center text-xs text-faint">
          No specialists matched yet — connect a repo or set the stack.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {(recommended ?? []).map((a) => (
            <SpecialistCard key={a.slug} agent={a} recommended />
          ))}
        </div>
      )}

      <div className="mt-6">
        <Eyebrow>Full marketplace</Eyebrow>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {catalog
            .filter((a) => !recSlugs.has(a.slug))
            .map((a) => (
              <SpecialistCard key={a.slug} agent={a} />
            ))}
        </div>
      </div>
    </div>
  );
}

function SpecialistCard({ agent, recommended = false }: { agent: MarketplaceAgent; recommended?: boolean }) {
  return (
    <div
      className="flex items-center gap-3 rounded-card border bg-raised/30 p-3"
      style={{ borderColor: recommended ? "#5B8CFF44" : "#262A38" }}
    >
      <div
        className="grid h-9 w-9 shrink-0 place-items-center rounded-[9px] text-base"
        style={{ background: recommended ? "#5B8CFF18" : "#1C1F2A", color: recommended ? "#5B8CFF" : "#A0A6B8" }}
      >
        {SPECIALIST_GLYPH[agent.slug] ?? "●"}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">{agent.title}</p>
        <p className="truncate text-xs text-muted">{agent.expertise}</p>
      </div>
      {recommended && <Badge color="#5B8CFF">match</Badge>}
    </div>
  );
}
