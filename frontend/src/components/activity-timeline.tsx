"use client";

import { ROLE_LABEL } from "@/types";
import type { ActivityEvent } from "@/types";
import { clockTime, roleColor } from "@/lib/utils";
import { StatusDot } from "@/components/ui";

const EVENT_GLYPH: Record<string, string> = {
  agent_started: "▸",
  agent_step: "·",
  agent_succeeded: "✓",
  agent_failed: "✕",
  task_created: "+",
  pr_opened: "⇪",
  pr_merged: "⌥",
  deploy_started: "⬡",
  deploy_succeeded: "⬢",
  approval_requested: "⏸",
};

function glyph(type: string): string {
  return EVENT_GLYPH[type] ?? "•";
}

export function ActivityTimeline({
  events,
  connected,
}: {
  events: ActivityEvent[];
  connected: boolean;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
        <div className="flex items-baseline gap-2.5">
          <h2 className="text-sm font-semibold tracking-tight text-ink">Activity</h2>
          <span className="font-mono text-xs text-faint">live stream</span>
        </div>
        <div className="flex items-center gap-1.5">
          <StatusDot color={connected ? "#5FD17A" : "#454C61"} pulse={connected} size={6} />
          <span className="font-mono text-[0.6875rem] uppercase text-muted">
            {connected ? "connected" : "polling"}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2">
        {events.length === 0 ? (
          <p className="px-3 py-10 text-center text-sm text-muted">
            No activity yet. Start a project and the agents will report in here.
          </p>
        ) : (
          <ol className="relative">
            {/* spine */}
            <span className="absolute bottom-3 left-[1.35rem] top-3 w-px bg-line" aria-hidden />
            {events.map((e) => {
              const color = roleColor(e.agent_role);
              return (
                <li
                  key={e.id}
                  className="relative flex animate-slide-up gap-3 rounded-lg px-3 py-2 hover:bg-raised/40"
                >
                  <div
                    className="relative z-10 mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border bg-panel font-mono text-xs"
                    style={{ borderColor: `${color}55`, color }}
                  >
                    {glyph(e.event_type)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-snug text-ink">{e.message}</p>
                    <div className="mt-0.5 flex items-center gap-2">
                      {e.agent_role && (
                        <span className="font-mono text-[0.625rem] uppercase" style={{ color }}>
                          {ROLE_LABEL[e.agent_role]}
                        </span>
                      )}
                      <span className="font-mono text-[0.625rem] text-faint">
                        {clockTime(e.created_at)}
                      </span>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}
