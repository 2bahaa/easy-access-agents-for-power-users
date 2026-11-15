import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Approval } from "../../api/types";
import { ApprovalCard } from "../../components/ApprovalCard";
import { initialRunState, runReducer } from "../../lib/runReducer";
import { agent } from "../../test/fixtures";
import { ME, mockApi, renderApp } from "../../test/render";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };
const APPROVAL: Approval = {
  id: "ap-1", run_id: "r-1", conversation_id: "c-1", agent_id: "a-1", call_id: "call-1", tool_name: "calculator",
  args: { expression: "6*7" }, status: "pending", edited_args: null, decided_by: null, decided_at: null, note: "",
  created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 3600_000).toISOString(),
};

describe("ApprovalCard", () => {
  it("approves, edits arguments (validated as JSON) and rejects with a note", async () => {
    const onDecide = vi.fn();
    render(<ApprovalCard approval={APPROVAL} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onDecide).toHaveBeenLastCalledWith({ approve: true });

    await userEvent.click(screen.getByRole("button", { name: "Edit arguments" }));
    const box = screen.getByLabelText("Arguments (JSON)");
    await userEvent.clear(box);
    await userEvent.type(box, "not json");
    await userEvent.click(screen.getByRole("button", { name: "Approve with changes" }));
    expect(screen.getByText("Arguments must be a JSON object.")).toBeInTheDocument();
    await userEvent.clear(box);
    await userEvent.type(box, '{{"expression": "1+1"}');
    await userEvent.click(screen.getByRole("button", { name: "Approve with changes" }));
    expect(onDecide).toHaveBeenLastCalledWith({ approve: true, args: { expression: "1+1" } });

    await userEvent.type(screen.getByLabelText("Note (optional)"), "too risky");
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(onDecide).toHaveBeenLastCalledWith({ approve: false, note: "too risky" });
  });

  it("is read-only when disabled", () => {
    render(<ApprovalCard approval={APPROVAL} onDecide={vi.fn()} disabled />);
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });
});

describe("run reducer approval events", () => {
  it("records held calls and the paused state", () => {
    const base = { run_id: "r-1", ts: "" };
    let s = runReducer(initialRunState, { type: "run.started", seq: 1, agent_id: "a", model: "m", ...base } as never);
    s = runReducer(s, { type: "approval.requested", seq: 2, call_id: "c", tool: "calculator", args: { x: 1 }, ...base } as never);
    s = runReducer(s, { type: "run.waiting_approval", seq: 3, pending: ["c"], ...base } as never);
    expect(s.status).toBe("waiting_approval");
    expect(s.items.map((i) => i.kind)).toEqual(["started", "approval", "end"]);
  });
});

describe("Approvals in the app", () => {
  it("shows a pending approval in the chat and decides it", async () => {
    let decided = false;
    const conversation = {
      id: "c-1", agent_id: "a-1", title: "Compute", created_at: "", updated_at: "",
      messages: [{ id: "m-1", run_id: "r-1", seq: 1, role: "user", content: "compute", tool_calls: null, tool_call_id: null, tool_name: null, created_at: "" }],
      runs: [{ id: "r-1", conversation_id: "c-1", agent_id: "a-1", status: "waiting_approval", tool_call_count: 0, usage: {}, error: null, started_at: "", finished_at: null }],
    };
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /agents/a-1": agent,
      "GET /conversations?agent_id=a-1": [conversation],
      "GET /conversations/c-1": conversation,
      "GET /approvals?status=pending&conversation_id=c-1": () => (decided ? [] : [APPROVAL]),
      "GET /approvals?status=pending": () => (decided ? [] : [APPROVAL]),
      "POST /approvals/ap-1/decide": () => {
        decided = true;
        return { approval: { ...APPROVAL, status: "approved" }, continuation_run_id: "r-2" };
      },
    });
    renderApp("/agents/a-1/chat/c-1");
    const panel = await screen.findByLabelText("Pending approvals");
    expect(within(panel).getByText(/Calculator wants to run/)).toBeInTheDocument();
    expect(screen.getByLabelText("1 pending")).toBeInTheDocument(); // nav badge
    await userEvent.click(within(panel).getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/approvals/ap-1/decide")?.body).toEqual({ decision: "approve", args: null, note: "" }),
    );
    await waitFor(() => expect(screen.queryByLabelText("Pending approvals")).toBeNull());
  });

  it("manages workspace policies (admins)", async () => {
    let policies: unknown[] = [];
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /agents": [],
      "GET /approvals?status=pending": [],
      "GET /approval-policies": () => policies,
      "POST /approval-policies": () => {
        policies = [{ id: "p-1", tool_pattern: "http__*", agent_id: null, created_at: "" }];
        return policies[0];
      },
    });
    renderApp("/approvals");
    expect(await screen.findByText("Nothing to review")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Policies" }));
    await userEvent.type(screen.getByLabelText(/Tool pattern/), "http__*");
    await userEvent.click(screen.getByRole("button", { name: "Add policy" }));
    expect(await screen.findByText("http__*", { selector: "code" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/approval-policies" && c.method === "POST")?.body).toEqual({ tool_pattern: "http__*", agent_id: null });
  });

  it("hides policies from non-admins", async () => {
    mockApi({ "GET /health": HEALTH, "GET /auth/me": { ...ME, role: "editor" }, "GET /agents": [], "GET /approvals?status=pending": [] });
    renderApp("/approvals");
    expect(await screen.findByRole("tab", { name: "Pending" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Policies" })).toBeNull();
  });
});
