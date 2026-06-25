"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Boxes,
  CircuitBoard,
  GitPullRequest,
  Layers,
  LayoutDashboard,
  LogOut,
} from "lucide-react";
import { clearToken } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Operations", icon: LayoutDashboard },
  { href: "/fleet", label: "Fleet (OS)", icon: Layers },
  { href: "/projects", label: "Projects", icon: Boxes },
  { href: "/agents", label: "The Floor", icon: CircuitBoard },
];

function BrandMark() {
  return (
    <Link href="/" className="flex items-center gap-2.5 px-2">
      <span className="relative grid h-8 w-8 place-items-center rounded-[10px] bg-gradient-to-br from-signal to-[#3a5fd9] shadow-glow">
        <span className="font-mono text-sm font-bold text-void">R</span>
      </span>
      <span className="flex flex-col leading-none">
        <span className="text-[15px] font-semibold tracking-tight text-ink">RiMo</span>
        <span className="text-eyebrow font-mono text-faint">AI SOFTWARE CO.</span>
      </span>
    </Link>
  );
}

export function AppShell({
  children,
  user,
}: {
  children: React.ReactNode;
  user?: { email: string; full_name: string | null } | null;
}) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-line bg-panel/60 px-3 py-5">
        <BrandMark />

        <nav className="mt-8 flex flex-col gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "group flex items-center gap-3 rounded-[10px] px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-raised text-ink"
                    : "text-muted hover:bg-raised/60 hover:text-ink",
                )}
              >
                <Icon
                  size={17}
                  className={active ? "text-signal" : "text-faint group-hover:text-muted"}
                />
                {label}
                {active && (
                  <span className="ml-auto h-1.5 w-1.5 rounded-full bg-signal" />
                )}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto space-y-3">
          <div className="flex items-center gap-2 rounded-[10px] border border-line bg-raised/40 px-3 py-2">
            <Activity size={14} className="text-ok" />
            <span className="font-mono text-xs text-muted">company online</span>
            <span className="ml-auto h-1.5 w-1.5 animate-breathe rounded-full bg-ok" />
          </div>

          <div className="flex items-center gap-2 px-2">
            <div className="grid h-7 w-7 place-items-center rounded-full bg-raised font-mono text-xs text-muted">
              {(user?.full_name ?? user?.email ?? "?").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-ink">
                {user?.full_name ?? "Operator"}
              </p>
              <p className="truncate font-mono text-[0.6875rem] text-faint">
                {user?.email ?? ""}
              </p>
            </div>
            <button
              onClick={() => {
                clearToken();
                window.location.href = "/login";
              }}
              className="rounded-md p-1.5 text-faint transition-colors hover:bg-raised hover:text-danger"
              aria-label="Sign out"
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </aside>

      <main className="relative min-w-0 flex-1">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-64 bg-grid opacity-60" />
        <div className="relative mx-auto max-w-[1400px] px-8 py-7">{children}</div>
      </main>
    </div>
  );
}

export { GitPullRequest };
