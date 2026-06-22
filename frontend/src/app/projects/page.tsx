"use client";

import Link from "next/link";
import { useState } from "react";
import { Boxes, Github, Plus, Sparkles, X } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, EmptyState, Eyebrow, Panel, StatusDot } from "@/components/ui";
import { useAuth, usePolling } from "@/hooks";
import { api, ApiError } from "@/lib/api";
import type { Project } from "@/types";
import { relativeTime } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  active: "#5FD17A",
  analyzing: "#5B8CFF",
  paused: "#F2C14E",
  blocked: "#E5544B",
  draft: "#6E7891",
  archived: "#454C61",
};

export default function ProjectsPage() {
  const { user, ready } = useAuth();
  const { data: projects, refetch } = usePolling<Project[]>(() => api.projects(), 8000);
  const [open, setOpen] = useState(false);

  if (!ready) return null;

  return (
    <AppShell user={user}>
      <header className="mb-7 flex items-end justify-between">
        <div>
          <Eyebrow>Portfolio</Eyebrow>
          <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">Projects</h1>
          <p className="mt-1 text-sm text-muted">
            Every project gets its own ten-agent company working toward the mission.
          </p>
        </div>
        <Button variant="primary" onClick={() => setOpen(true)}>
          <Plus size={15} />
          New project
        </Button>
      </header>

      {!projects || projects.length === 0 ? (
        <Panel>
          <EmptyState
            icon={<Boxes size={28} />}
            title="No projects yet"
            hint="Point RiMo at a GitHub repository or describe a new idea. The CEO agent sets the mission, the Planner breaks it into tasks, and the company starts shipping."
            action={
              <Button variant="primary" onClick={() => setOpen(true)}>
                Create your first project
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((p) => (
            <Link key={p.id} href={`/projects/${p.id}`}>
              <Panel className="group h-full p-5 transition-colors hover:border-faint">
                <div className="flex items-start justify-between">
                  <StatusDot color={STATUS_TONE[p.status] ?? "#6E7891"} pulse={p.is_running} />
                  <Badge color={STATUS_TONE[p.status]}>{p.status}</Badge>
                </div>
                <h2 className="mt-3 text-base font-semibold tracking-tight text-ink">
                  {p.name}
                </h2>
                <p className="mt-1 line-clamp-2 min-h-[2.5rem] text-sm text-muted">
                  {p.mission ?? p.description ?? "Mission not yet set."}
                </p>
                <div className="mt-4 flex items-center justify-between border-t border-line pt-3">
                  <span className="flex items-center gap-1.5 font-mono text-[0.6875rem] text-faint">
                    <Github size={12} />
                    {p.repo_full_name ?? "greenfield"}
                  </span>
                  <span className="font-mono text-[0.6875rem] text-faint">
                    {relativeTime(p.updated_at)}
                  </span>
                </div>
              </Panel>
            </Link>
          ))}
        </div>
      )}

      {open && (
        <CreateProjectDialog
          onClose={() => setOpen(false)}
          onCreated={() => {
            setOpen(false);
            void refetch();
          }}
        />
      )}
    </AppShell>
  );
}

function CreateProjectDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [mission, setMission] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await api.createProject({
        name: name.trim(),
        repo_url: repoUrl.trim() || undefined,
        mission: mission.trim() || undefined,
      });
      onCreated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to create project");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-void/70 px-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-card border border-line bg-panel shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-signal" />
            <h2 className="text-sm font-semibold text-ink">New project</h2>
          </div>
          <button onClick={onClose} className="text-faint hover:text-ink">
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <Field label="Project name" value={name} onChange={setName} placeholder="Acme Payments API" />
          <Field
            label="GitHub repository (optional)"
            value={repoUrl}
            onChange={setRepoUrl}
            placeholder="https://github.com/acme/payments"
          />
          <div>
            <span className="text-eyebrow font-mono uppercase text-muted">
              Mission (optional)
            </span>
            <textarea
              value={mission}
              onChange={(e) => setMission(e.target.value)}
              placeholder="What should this company achieve? Leave blank to let the CEO agent propose one."
              rows={3}
              className="mt-1.5 w-full resize-none rounded-lg border border-line bg-raised px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-signal/60"
            />
          </div>

          {error && (
            <p className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
              {error}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-5 py-4">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={create} disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create project"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="text-eyebrow font-mono uppercase text-muted">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1.5 w-full rounded-lg border border-line bg-raised px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-signal/60"
      />
    </label>
  );
}
