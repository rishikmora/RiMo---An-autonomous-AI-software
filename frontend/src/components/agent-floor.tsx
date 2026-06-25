"use client";

import { ROLE_LABEL, ROLE_MANDATE, ALL_ROLES } from "@/types";
import type { AgentRole, AgentView } from "@/types";
import { cn, compactNumber, relativeTime, roleColor, STATUS_TONE } from "@/lib/utils";
import { StatusDot } from "@/components/ui";

const ROLE_GLYPH: Record<AgentRole, string> = {
  ceo: "◆",
  research: "◇",
  planner: "▦",
  architect: "△",
  builder: "▣",
  reviewer: "◎",
  qa: "✓",
  security: "⛨",
  devops: "⬢",
  memory: "❖",
};

export function AgentFloor({
  agents,
  compact = false,
}: {
  agents: AgentView[];
  compact?: boolean;
}) {
  const byRole = new Map(agents.map((a) => [a.role, a]));

  return (
    <div
      className={cn(
        "grid gap-2.5",
        compact ? "grid-cols-2 sm:grid-cols-5" : "grid-cols-2 md:grid-cols-3 xl:grid-cols-5",
      )}
    >
      {ALL_ROLES.map((role) => {
        const agent = byRole.get(role);
        const status = agent?.status ?? "offline";
        const tone = STATUS_TONE[status];
        const color = roleColor(role);
        const live = status === "thinking" || status === "working";

        return (
          <div
            key={role}
            className={cn(
              "group relative overflow-hidden rounded-card border bg-panel p-3.5 transition-colors",
              live ? "border-line" : "border-line/60",
            )}
            style={live ? { boxShadow: `inset 0 0 0 1px ${color}22` } : undefined}
          >
            {/* live sweep highlight while the agent is active */}
            {live && (
              <div className="pointer-events-none absolute inset-x-0 top-0 h-px overflow-hidden">
                <div
                  className="h-px w-1/3 animate-sweep"
                  style={{ background: `linear-gradient(90deg, transparent, ${color}, transparent)` }}
                />
              </div>
            )}

            <div className="flex items-start justify-between">
              <div
                className="grid h-8 w-8 place-items-center rounded-[9px] text-base"
                style={{ background: `${color}18`, color }}
              >
                {ROLE_GLYPH[role]}
              </div>
              <StatusDot color={tone.dot} pulse={live} size={7} />
            </div>

            <div className="mt-2.5">
              <p className="text-sm font-semibold tracking-tight text-ink">
                RiMo {ROLE_LABEL[role]}
              </p>
              <p className="mt-0.5 text-xs text-muted">{ROLE_MANDATE[role]}</p>
            </div>

            <div className="mt-3 flex items-center justify-between border-t border-line/70 pt-2.5">
              <span
                className="font-mono text-[0.6875rem] uppercase tracking-wide"
                style={{ color: tone.dot }}
              >
                {tone.label}
              </span>
              <span className="font-mono text-[0.6875rem] text-faint">
                {agent ? `${compactNumber(agent.total_runs)} runs` : "—"}
              </span>
            </div>

            {!compact && (
              <div className="mt-1 flex items-center justify-between">
                <span className="font-mono text-[0.625rem] text-faint">
                  {agent ? `${compactNumber(agent.total_tokens)} tok` : ""}
                </span>
                <span className="font-mono text-[0.625rem] text-faint">
                  {agent?.last_heartbeat ? relativeTime(agent.last_heartbeat) : ""}
                </span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
