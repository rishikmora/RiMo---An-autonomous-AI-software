import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { AgentRole, AgentStatus, Priority, TaskStatus } from "@/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const s = Math.round(diff / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

const ROLE_HEX: Record<AgentRole, string> = {
  ceo: "#F2C14E",
  research: "#8B7FF5",
  planner: "#5B8CFF",
  architect: "#4EC3C1",
  builder: "#5FD17A",
  reviewer: "#F08A5D",
  qa: "#E36AA8",
  security: "#E5544B",
  devops: "#3FB4E8",
  memory: "#A0A6B8",
};

export function roleColor(role: AgentRole | null | undefined): string {
  return role ? ROLE_HEX[role] : "#6E7891";
}

export const STATUS_TONE: Record<AgentStatus, { dot: string; label: string }> = {
  idle: { dot: "#454C61", label: "Idle" },
  thinking: { dot: "#5B8CFF", label: "Thinking" },
  working: { dot: "#5FD17A", label: "Working" },
  waiting: { dot: "#F2C14E", label: "Waiting" },
  error: { dot: "#E5544B", label: "Error" },
  offline: { dot: "#2A2E3C", label: "Offline" },
};

export const TASK_TONE: Record<TaskStatus, string> = {
  backlog: "#6E7891",
  ready: "#5B8CFF",
  in_progress: "#5FD17A",
  in_review: "#F08A5D",
  blocked: "#E5544B",
  done: "#3FB4E8",
  cancelled: "#454C61",
  failed: "#E5544B",
};

export const PRIORITY_LABEL: Record<Priority, string> = {
  0: "Critical",
  1: "High",
  2: "Medium",
  3: "Low",
};

export const PRIORITY_TONE: Record<Priority, string> = {
  0: "#E5544B",
  1: "#F2C14E",
  2: "#5B8CFF",
  3: "#6E7891",
};

export function compactNumber(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}
