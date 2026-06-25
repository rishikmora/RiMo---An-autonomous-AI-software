import * as React from "react";
import { cn } from "@/lib/utils";

export function Panel({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-card border border-line bg-panel shadow-panel",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function PanelHeader({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
      <div className="flex items-baseline gap-2.5">
        <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
        {hint ? <span className="font-mono text-xs text-faint">{hint}</span> : null}
      </div>
      {action}
    </div>
  );
}

export function Eyebrow({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("text-eyebrow font-mono uppercase text-muted", className)}>{children}</span>
  );
}

export function StatusDot({
  color,
  pulse = false,
  size = 8,
}: {
  color: string;
  pulse?: boolean;
  size?: number;
}) {
  return (
    <span className="relative inline-flex" style={{ width: size, height: size }}>
      {pulse && (
        <span
          className="absolute inset-0 rounded-full animate-breathe"
          style={{ background: color }}
        />
      )}
      <span
        className="relative inline-block rounded-full"
        style={{ width: size, height: size, background: color }}
      />
    </span>
  );
}

export function Badge({
  children,
  color,
  className,
}: {
  children: React.ReactNode;
  color?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-pill border px-2 py-0.5 font-mono text-[0.6875rem] uppercase tracking-wide",
        className,
      )}
      style={
        color
          ? { borderColor: `${color}44`, color, background: `${color}11` }
          : { borderColor: "#262A38", color: "#6E7891" }
      }
    >
      {children}
    </span>
  );
}

export function Stat({
  label,
  value,
  accent,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  accent?: string;
  sub?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Eyebrow>{label}</Eyebrow>
      <span
        className="font-mono text-2xl font-semibold tabular-nums leading-none"
        style={{ color: accent ?? "#E8EAF0" }}
      >
        {value}
      </span>
      {sub ? <span className="text-xs text-muted">{sub}</span> : null}
    </div>
  );
}

export function Button({
  children,
  variant = "default",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "ghost" | "danger";
}) {
  const styles: Record<string, string> = {
    default: "border-line bg-raised text-ink hover:border-faint hover:bg-[#23273400]",
    primary: "border-signal/40 bg-signal/15 text-signal hover:bg-signal/25",
    ghost: "border-transparent text-muted hover:text-ink hover:bg-raised",
    danger: "border-danger/40 bg-danger/10 text-danger hover:bg-danger/20",
  };
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-pill border px-3.5 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        styles[variant],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      {icon ? <div className="text-faint">{icon}</div> : null}
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">{title}</p>
        {hint ? <p className="max-w-sm text-sm text-muted">{hint}</p> : null}
      </div>
      {action}
    </div>
  );
}
