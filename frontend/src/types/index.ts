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

// --- Intelligence layer (Tier 1–4 subsystems) ---

export interface CostSummary {
  total_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  calls: number;
  by_model: Record<string, number>;
  by_agent: Record<string, number>;
  cost_per_completed_task: number | null;
  cost_per_merged_pr: number | null;
  naive_baseline_usd: number;
  routing_savings_usd: number;
  routing_savings_pct: number;
}

export type NodeKind =
  | "module"
  | "file"
  | "class"
  | "function"
  | "api_route"
  | "db_table"
  | "service"
  | "external";

export interface GraphNodeData {
  id: string;
  kind: NodeKind;
  key: string;
  name: string;
  path: string | null;
  centrality: number;
  summary: string | null;
}

export interface GraphEdgeData {
  source: string;
  target: string;
  kind: string;
  weight: number;
}

export interface GraphData {
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
  stats: { nodes: number; edges: number };
}

export interface CentralNode {
  name: string;
  kind: NodeKind;
  path: string | null;
  centrality: number;
}

export type IncidentStatus =
  | "open"
  | "diagnosing"
  | "recovered"
  | "rolled_back"
  | "escalated";

export interface IncidentStep {
  kind: string;
  detail: string;
  at: string;
}

export interface Incident {
  id: string;
  title: string;
  trigger: string;
  status: IncidentStatus;
  attempts: number;
  diagnosis: string | null;
  resolution: string | null;
  timeline: IncidentStep[];
  created_at: string;
}

export interface SpendCall {
  model: string;
  provider: string;
  cost_usd: number;
  tokens: number;
  purpose: string | null;
}

export interface SpendData {
  total_usd: number;
  recent_calls: SpendCall[];
}

export interface PromptVariantStat {
  name: string;
  generation: number;
  active: boolean;
  trials: number;
  successes: number;
  success_rate: number;
  mean_reward: number;
}

export interface ProjectHealth {
  project_id: string;
  name: string;
  status: ProjectStatus;
  open_tasks: number;
  pending_approvals: number;
  is_running: boolean;
  attention_score: number;
}

export interface FleetView {
  total_projects: number;
  running: number;
  blocked: number;
  total_open_tasks: number;
  total_pending_approvals: number;
  projects: ProjectHealth[];
}

export interface Smell {
  kind: string;
  node_name: string;
  metric: string;
  severity: number;
  suggestion: string;
  members: string[];
}

export interface MarketplaceAgent {
  slug: string;
  title: string;
  expertise: string;
  triggers?: string[];
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
