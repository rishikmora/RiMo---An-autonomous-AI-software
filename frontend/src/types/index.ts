// Domain types mirroring the RiMo backend (app/schemas, app/models/enums).

export type AgentRole =
  | "ceo"
  | "research"
  | "planner"
  | "architect"
  | "builder"
  | "reviewer"
  | "qa"
  | "security"
  | "devops"
  | "memory";

export type AgentStatus =
  | "idle"
  | "thinking"
  | "working"
  | "waiting"
  | "error"
  | "offline";

export type ProjectStatus =
  | "draft"
  | "analyzing"
  | "active"
  | "paused"
  | "blocked"
  | "archived";

export type TaskStatus =
  | "backlog"
  | "ready"
  | "in_progress"
  | "in_review"
  | "blocked"
  | "done"
  | "cancelled"
  | "failed";

export type TaskKind =
  | "feature"
  | "bugfix"
  | "refactor"
  | "test"
  | "security"
  | "performance"
  | "docs"
  | "infra"
  | "research";

export type Priority = 0 | 1 | 2 | 3; // critical, high, medium, low

export type PullRequestStatus =
  | "open"
  | "approved"
  | "changes_requested"
  | "merged"
  | "closed";

export type DeploymentStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "rolled_back";

export type ApprovalKind =
  | "merge"
  | "deploy"
  | "repo_delete"
  | "destructive_migration";

export interface DashboardSummary {
  projects_active: number;
  agents_running: number;
  tasks_queued: number;
  prs_open: number;
  deployments_today: number;
  pending_approvals: number;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  status: ProjectStatus;
  repo_full_name: string | null;
  repo_url: string | null;
  default_branch: string;
  primary_language: string | null;
  mission: string | null;
  objectives: Record<string, unknown>;
  autonomy_level: number;
  is_running: boolean;
  architecture_summary: string | null;
  metrics: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AgentView {
  id: string;
  role: AgentRole;
  status: AgentStatus;
  current_task_id: string | null;
  last_heartbeat: string | null;
  total_runs: number;
  total_tokens: number;
}

export interface Task {
  id: string;
  project_id: string;
  parent_id: string | null;
  title: string;
  description: string | null;
  kind: TaskKind;
  status: TaskStatus;
  priority: Priority;
  complexity: number;
  assigned_role: AgentRole | null;
  branch_name: string | null;
  acceptance_criteria: string[];
  attempts: number;
  github_issue_number: number | null;
  created_at: string;
  updated_at: string;
}

export interface PullRequest {
  id: string;
  number: number;
  title: string;
  body: string | null;
  head_branch: string;
  base_branch: string;
  status: PullRequestStatus;
  files_changed: number;
  additions: number;
  deletions: number;
  review_summary: string | null;
  review_score: number | null;
  checks_passing: boolean;
  merged_at: string | null;
  created_at: string;
}

export interface Deployment {
  id: string;
  environment: string;
  commit_sha: string | null;
  status: DeploymentStatus;
  url: string | null;
  duration_seconds: number | null;
  created_at: string;
}

export interface MemoryRecord {
  id: string;
  kind: string;
  title: string;
  content: string;
  importance: number;
  access_count: number;
  created_at: string;
}

export interface Approval {
  id: string;
  kind: ApprovalKind;
  subject_id: string | null;
  summary: string;
  payload: Record<string, unknown>;
  approved: boolean | null;
  created_at: string;
}

export interface ActivityEvent {
  id: number;
  project_id: string;
  agent_role: AgentRole | null;
  event_type: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface ProjectMetrics {
  tasks_total: number;
  tasks_done: number;
  tasks_in_progress: number;
  open_prs: number;
  merged_prs: number;
  deployments_succeeded: number;
  agents_active: number;
  velocity_7d: number;
  avg_review_score: number | null;
}

export const ALL_ROLES: AgentRole[] = [
  "ceo",
  "research",
  "planner",
  "architect",
  "builder",
  "reviewer",
  "qa",
  "security",
  "devops",
  "memory",
];

export const ROLE_LABEL: Record<AgentRole, string> = {
  ceo: "CEO",
  research: "Research",
  planner: "Planner",
  architect: "Architect",
  builder: "Builder",
  reviewer: "Reviewer",
  qa: "QA",
  security: "Security",
  devops: "DevOps",
  memory: "Memory",
};

export const ROLE_MANDATE: Record<AgentRole, string> = {
  ceo: "Mission & strategy",
  research: "Docs & prior art",
  planner: "Roadmap & tasks",
  architect: "System design",
  builder: "Writes the code",
  reviewer: "Code review",
  qa: "Tests everything",
  security: "Scans & secrets",
  devops: "Ship & roll back",
  memory: "Learns & recalls",
};
