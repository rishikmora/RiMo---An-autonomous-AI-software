"use client";

import { useState } from "react";
import { api, ApiError, getToken } from "@/lib/api";
import { Button, Eyebrow } from "@/components/ui";
import { useEffect } from "react";

export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (getToken()) window.location.href = "/";
  }, []);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await api.login(email, password);
      else await api.register(email, password, name || undefined);
      window.location.href = "/";
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative grid min-h-screen place-items-center px-4">
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-40" />
      <div className="pointer-events-none absolute left-1/2 top-1/3 h-72 w-72 -translate-x-1/2 rounded-full bg-signal/10 blur-3xl" />

      <div className="relative w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="grid h-12 w-12 place-items-center rounded-[14px] bg-gradient-to-br from-signal to-[#3a5fd9] shadow-glow">
            <span className="font-mono text-lg font-bold text-void">R</span>
          </span>
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink">RiMo</h1>
            <p className="text-eyebrow mt-1 font-mono text-faint">AUTONOMOUS SOFTWARE COMPANY</p>
          </div>
        </div>

        <div className="rounded-card border border-line bg-panel p-6 shadow-panel">
          <Eyebrow>{mode === "login" ? "Sign in" : "Create account"}</Eyebrow>
          <div className="mt-4 space-y-3">
            {mode === "register" && (
              <Field label="Name" value={name} onChange={setName} placeholder="Rishik Mora" />
            )}
            <Field
              label="Email"
              type="email"
              value={email}
              onChange={setEmail}
              placeholder="you@company.com"
            />
            <Field
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              placeholder="••••••••"
              onEnter={submit}
            />

            {error && (
              <p className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
                {error}
              </p>
            )}

            <Button
              variant="primary"
              className="w-full justify-center"
              onClick={submit}
              disabled={busy || !email || !password}
            >
              {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </div>

          <button
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
            }}
            className="mt-4 w-full text-center text-xs text-muted transition-colors hover:text-ink"
          >
            {mode === "login"
              ? "No account? Create one"
              : "Already have an account? Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  onEnter,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  onEnter?: () => void;
}) {
  return (
    <label className="block">
      <span className="text-eyebrow font-mono uppercase text-muted">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
        className="mt-1.5 w-full rounded-lg border border-line bg-raised px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-signal/60"
      />
    </label>
  );
}
