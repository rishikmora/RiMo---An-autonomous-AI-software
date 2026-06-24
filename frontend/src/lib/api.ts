// Typed client for the RiMo API. In the browser, requests go through Next's
// rewrite proxy (/api/* -> backend), so a relative base works everywhere.
import type {
  ActivityEvent,
  AgentView,
  Approval,
  CentralNode,
  CostSummary,
  DashboardSummary,
  Deployment,
  FleetView,
  GraphData,
  Incident,
  MarketplaceAgent,
  MemoryRecord,
  Project,
  ProjectMetrics,
  PullRequest,
  Smell,
  SpendData,
  Task,
} from "@/types";

const TOKEN_KEY = "rimo_token";
const REFRESH_KEY = "rimo_refresh";
const V1 = "/api/v1";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}
export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REFRESH_KEY);
}
export function setTokens(access: string, refresh: string) {
  window.localStorage.setItem(TOKEN_KEY, access);
  window.localStorage.setItem(REFRESH_KEY, refresh);
}
export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
}

// Transparent refresh: serialize concurrent 401s onto one in-flight refresh.
let refreshInFlight: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${V1}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
          cache: "no-store",
        });
        if (!res.ok) return false;
        const data = (await res.json()) as { access_token: string; refresh_token: string };
        setTokens(data.access_token, data.refresh_token);
        return true;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}, _retried = false): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(path, { ...init, headers, cache: "no-store" });
  if (res.status === 401) {
    // Try one transparent refresh before giving up and redirecting to login.
    if (!_retried && (await tryRefresh())) {
      return request<T>(path, init, true);
    }
    clearToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  // --- auth ---
  async login(email: string, password: string) {
    // Backend uses OAuth2 password flow: form-encoded, `username` field.
    const form = new URLSearchParams({ username: email, password });
    const res = await fetch(`${V1}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
      cache: "no-store",
    });
    if (!res.ok) {
      let detail = "Incorrect email or password";
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* keep default */
      }
      throw new ApiError(res.status, detail);
    }
    const data = (await res.json()) as { access_token: string; refresh_token: string };
    setTokens(data.access_token, data.refresh_token);
    return data;
  },
  async register(email: string, password: string, full_name?: string) {
    // Register creates the user; then we log in to obtain a token pair.
    await request(`${V1}/auth/register`, {
      method: "POST",
      body: JSON.stringify({ email, password, full_name }),
    });
    return api.login(email, password);
  },
  async logout() {
    const refresh = getRefreshToken();
    if (refresh) {
      try {
        await fetch(`${V1}/auth/logout`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
      } catch {
        /* best-effort */
      }
    }
    clearToken();
  },
  me: () => request<{ id: string; email: string; full_name: string | null }>(`${V1}/auth/me`),

  // --- dashboard ---
  dashboard: () => request<DashboardSummary>(`${V1}/dashboard/summary`),

  // --- projects ---
  projects: () => request<Project[]>(`${V1}/projects`),
  project: (id: string) => request<Project>(`${V1}/projects/${id}`),
  createProject: (body: {
    name: string;
    description?: string;
    repo_url?: string;
    mission?: string;
  }) => request<Project>(`${V1}/projects`, { method: "POST", body: JSON.stringify(body) }),
  startProject: (id: string) =>
    request<Project>(`${V1}/projects/${id}/start`, { method: "POST" }),
  pauseProject: (id: string) =>
    request<Project>(`${V1}/projects/${id}/pause`, { method: "POST" }),
  planProject: (id: string, instruction?: string) =>
    request<{ created: number }>(`${V1}/projects/${id}/plan`, {
      method: "POST",
      body: JSON.stringify({ instruction: instruction ?? null }),
    }),

  // --- resources ---
  agents: (id: string) => request<AgentView[]>(`${V1}/projects/${id}/agents`),
  tasks: (id: string) => request<Task[]>(`${V1}/projects/${id}/tasks`),
  prs: (id: string) => request<PullRequest[]>(`${V1}/projects/${id}/pull-requests`),
  deployments: (id: string) => request<Deployment[]>(`${V1}/projects/${id}/deployments`),
  memory: (id: string) => request<MemoryRecord[]>(`${V1}/projects/${id}/memory`),
  approvals: (id: string) => request<Approval[]>(`${V1}/projects/${id}/approvals`),
  metrics: (id: string) => request<ProjectMetrics>(`${V1}/projects/${id}/metrics`),
  activity: (id: string, limit = 60) =>
    request<ActivityEvent[]>(`${V1}/projects/${id}/activity?limit=${limit}`),

  // --- actions ---
  decideApproval: (approvalId: string, approved: boolean) =>
    request<Approval>(`${V1}/approvals/${approvalId}/decide`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }),
  rollback: (deploymentId: string) =>
    request<Deployment>(`${V1}/deployments/${deploymentId}/rollback`, { method: "POST" }),

  // --- intelligence layer ---
  economics: (id: string) =>
    request<CostSummary>(`${V1}/projects/${id}/economics`),
  graph: (id: string) =>
    request<GraphData>(`${V1}/projects/${id}/graph`),
  centralNodes: (id: string) =>
    request<CentralNode[]>(`${V1}/projects/${id}/graph/central`),
  incidents: (id: string) =>
    request<Incident[]>(`${V1}/projects/${id}/incidents`),
  spend: (id: string) =>
    request<SpendData>(`${V1}/projects/${id}/spend`),
  triggerResearch: (id: string) =>
    request<{ status: string }>(`${V1}/projects/${id}/research`, { method: "POST" }),
  fleet: () => request<FleetView>(`${V1}/fleet`),
  smells: (id: string) => request<Smell[]>(`${V1}/projects/${id}/smells`),
  marketplace: () => request<MarketplaceAgent[]>(`${V1}/marketplace`),
  recommendedAgents: (id: string) =>
    request<MarketplaceAgent[]>(`${V1}/projects/${id}/marketplace/recommended`),
};

// Server-Sent Events stream of the activity timeline for a project.
export function streamUrl(projectId: string): string {
  const token = getToken();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${V1}/events/projects/${projectId}/stream${q}`;
}
