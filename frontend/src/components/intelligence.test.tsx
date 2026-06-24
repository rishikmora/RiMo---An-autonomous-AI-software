import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentFloor } from "@/components/agent-floor";
import { ApprovalQueue } from "@/components/project-tabs";
import type { AgentView, Approval } from "@/types";

describe("AgentFloor", () => {
  it("renders all ten company roles even with no agent data", () => {
    render(<AgentFloor agents={[]} />);
    // The floor always shows the full roster; labels are prefixed "RiMo".
    for (const role of ["CEO", "Research", "Planner", "Architect", "Builder", "Reviewer", "QA", "Security", "DevOps", "Memory"]) {
      expect(screen.getByText(`RiMo ${role}`)).toBeInTheDocument();
    }
  });

  it("reflects a working agent's status", () => {
    const agents: AgentView[] = [
      {
        id: "a1",
        role: "builder",
        status: "working",
        current_task_id: "t1",
        last_heartbeat: new Date().toISOString(),
        total_runs: 7,
        total_tokens: 12345,
      },
    ];
    render(<AgentFloor agents={agents} />);
    expect(screen.getByText("Working")).toBeInTheDocument();
    expect(screen.getByText(/7 runs/)).toBeInTheDocument();
  });
});

describe("ApprovalQueue — safety invariant", () => {
  const onDecide = vi.fn();

  it("shows nothing-to-approve state when there are no pending approvals", () => {
    // An already-decided approval must NOT surface approve/reject controls.
    const decided: Approval[] = [
      {
        id: "ap1",
        kind: "merge",
        subject_id: "pr1",
        summary: "Merge PR #1",
        payload: {},
        approved: true,
        created_at: new Date().toISOString(),
      },
    ];
    render(<ApprovalQueue approvals={decided} onDecide={onDecide} />);
    expect(screen.getByText(/Nothing awaiting approval/i)).toBeInTheDocument();
    // The merge approve/reject buttons must not exist.
    expect(screen.queryByRole("button", { name: /Approve/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Reject/i })).toBeNull();
  });

  it("surfaces approve/reject only for a pending approval", () => {
    const pending: Approval[] = [
      {
        id: "ap2",
        kind: "merge",
        subject_id: "pr2",
        summary: "Merge PR #2: add feature",
        payload: {},
        approved: null,
        created_at: new Date().toISOString(),
      },
    ];
    render(<ApprovalQueue approvals={pending} onDecide={onDecide} />);
    expect(screen.getByText(/Merge PR #2/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reject/i })).toBeInTheDocument();
  });
});
