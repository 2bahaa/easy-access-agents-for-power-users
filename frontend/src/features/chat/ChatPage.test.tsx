import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Conversation } from "../../api/types";
import { agent } from "../../test/fixtures";
import { mockApi, renderApp } from "../../test/render";
import { CALCULATOR_RUN, events, sseResponse, toSSE } from "../../test/stream";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };

/** The composer is disabled until the agent has loaded. */
async function composer() {
  const box = await screen.findByRole("textbox", { name: /Message/ });
  await waitFor(() => expect(box).toBeEnabled());
  return box;
}
const CHAT_AGENT = { ...agent, tools: [{ name: "calculator", config: {} }] };

const persistedConversation: Conversation = {
  id: "c-1",
  agent_id: "a-1",
  title: "What is 17.5 * 23 + 4?",
  created_at: "2026-11-14T10:00:00Z",
  updated_at: "2026-11-14T10:00:05Z",
  messages: [
    { id: "m-1", run_id: "r-1", seq: 1, role: "user", content: "What is 17.5 * 23 + 4?", tool_calls: null, tool_call_id: null, tool_name: null, created_at: "" },
    { id: "m-2", run_id: "r-1", seq: 2, role: "assistant", content: "", tool_calls: [{ id: "call-1", name: "calculator", args: { expression: "17.5 * 23 + 4" } }], tool_call_id: null, tool_name: null, created_at: "" },
    { id: "m-x", run_id: "r-1", seq: 3, role: "tool", content: "406.5", tool_calls: null, tool_call_id: "call-1", tool_name: "calculator", created_at: "" },
    { id: "m-3", run_id: "r-1", seq: 4, role: "assistant", content: "The answer is **406.5**.", tool_calls: null, tool_call_id: null, tool_name: null, created_at: "" },
  ],
  runs: [
    { id: "r-1", conversation_id: "c-1", agent_id: "a-1", status: "completed", tool_call_count: 1, usage: { total_tokens: 42 }, error: null, started_at: "", finished_at: "" },
  ],
};

const persistedEvents = CALCULATOR_RUN.filter((e) => e.type !== "message.delta").map((e) => {
  const { type, seq, run_id: _r, ts, ...payload } = e as unknown as Record<string, unknown>;
  return { type, seq, payload, created_at: ts };
});

describe("ChatPage", () => {
  it("starts a conversation, streams a run and then shows the persisted transcript", async () => {
    let persisted = false;
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /agents/a-1": CHAT_AGENT,
      "GET /conversations?agent_id=a-1": () => (persisted ? [persistedConversation] : []),
      "POST /conversations": { id: "c-1", agent_id: "a-1", title: "New conversation", created_at: "", updated_at: "" },
      "POST /conversations/c-1/messages": () => {
        persisted = true;
        return sseResponse(toSSE(CALCULATOR_RUN));
      },
      "GET /conversations/c-1": () => persistedConversation,
      "GET /runs/r-1/events": persistedEvents,
    });
    const { router } = renderApp("/agents/a-1/chat");

    const suggestion = await screen.findByRole("button", { name: "What is 17.5 * 23 + 4?" });
    await waitFor(() => expect(suggestion).toBeEnabled());
    await userEvent.click(suggestion);

    await waitFor(() => expect(router.state.location.pathname).toBe("/agents/a-1/chat/c-1"));
    const messages = await screen.findByRole("list", { name: "Messages" });
    expect(await within(messages).findByText("406.5", { selector: "strong" })).toBeInTheDocument();
    expect(within(messages).getByRole("button", { name: "Calculator tool call, completed" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/conversations/c-1/messages")?.body).toEqual({ content: "What is 17.5 * 23 + 4?" });

    // After the run, the timeline shows the persisted run.
    const timeline = (await screen.findAllByRole("list", { name: "Run timeline" }))[0]!;
    expect(await within(timeline).findByText("Completed")).toBeInTheDocument();
    // The user message is shown exactly once (live view replaced by persisted transcript).
    await waitFor(() => expect(within(messages).getAllByText("What is 17.5 * 23 + 4?")).toHaveLength(1));
  });

  it("loads an existing conversation with its history and timeline", async () => {
    mockApi({
      "GET /health": HEALTH,
      "GET /agents/a-1": CHAT_AGENT,
      "GET /conversations?agent_id=a-1": [persistedConversation],
      "GET /conversations/c-1": persistedConversation,
      "GET /runs/r-1/events": persistedEvents,
    });
    renderApp("/agents/a-1/chat/c-1");
    const messages = await screen.findByRole("list", { name: "Messages" });
    expect(await within(messages).findByText("What is 17.5 * 23 + 4?")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /What is 17.5/ })).toHaveAttribute("href", "/agents/a-1/chat/c-1");
    const timeline = (await screen.findAllByRole("list", { name: "Run timeline" }))[0]!;
    expect(await within(timeline).findByText("42 tokens")).toBeInTheDocument();
  });

  it("cancels a running run via the cancel endpoint", async () => {
    let release!: () => void;
    const hold = new Promise<void>((r) => (release = r));
    const startedOnly = events("r-9", [
      { type: "run.started", agent_id: "a-1", model: "qwen3:4b", conversation_id: "c-1", user_message_id: "m-1" },
    ]);
    const cancelled = events("r-9", [{ type: "run.cancelled" }]).map((e) => ({ ...e, seq: 2 }));
    const conversation = { ...persistedConversation, messages: [], runs: [] };
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /agents/a-1": CHAT_AGENT,
      "GET /conversations?agent_id=a-1": [conversation],
      "GET /conversations/c-1": conversation,
      "POST /conversations/c-1/messages": () => sseResponse(toSSE(startedOnly) + toSSE(cancelled), { holdOpen: hold, chunkSize: 10_000 }),
      "POST /runs/r-9/cancel": () => {
        release();
        return new Response(null, { status: 202 });
      },
    });
    renderApp("/agents/a-1/chat/c-1");
    await userEvent.type(await composer(), "Long task{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "Stop generating" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/runs/r-9/cancel")).toBe(true));
    expect(await screen.findByRole("button", { name: "Send message" })).toBeInTheDocument();
  });

  it("shows why a message could not be sent", async () => {
    const conversation = { ...persistedConversation, messages: [], runs: [] };
    mockApi({
      "GET /health": HEALTH,
      "GET /agents/a-1": CHAT_AGENT,
      "GET /conversations?agent_id=a-1": [conversation],
      "GET /conversations/c-1": conversation,
      "POST /conversations/c-1/messages": () =>
        new Response(JSON.stringify({ title: "Conflict", detail: "A run is already in progress for this conversation" }), { status: 409 }),
    });
    renderApp("/agents/a-1/chat/c-1");
    await userEvent.type(await composer(), "hello{Enter}");
    expect(await screen.findByText("A run is already in progress for this conversation", { selector: "p[role=alert]" })).toBeInTheDocument();
  });
  it("reattaches to a run that is still active on the server after a reload", async () => {
    let finished = false;
    const runningConversation: Conversation = {
      ...persistedConversation,
      messages: persistedConversation.messages.slice(0, 1),
      runs: [{ ...persistedConversation.runs[0]!, status: "running", finished_at: null }],
    };
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /agents/a-1": CHAT_AGENT,
      "GET /conversations?agent_id=a-1": [persistedConversation],
      "GET /conversations/c-1": () => (finished ? persistedConversation : runningConversation),
      "GET /runs/r-1/stream?after=0": () => {
        finished = true;
        return sseResponse(toSSE(CALCULATOR_RUN));
      },
      "GET /runs/r-1/events": persistedEvents,
    });
    renderApp("/agents/a-1/chat/c-1");

    // The live run is followed (not re-sent) and ends in the persisted transcript.
    expect((await screen.findAllByText("406.5", { exact: false })).length).toBeGreaterThan(0);
    await waitFor(() => expect(calls.some((c) => c.path === "/runs/r-1/stream?after=0")).toBe(true));
    expect(calls.filter((c) => c.method === "POST" && !c.path.startsWith("/auth/"))).toEqual([]);
    expect(calls.filter((c) => c.path.startsWith("/runs/r-1/stream"))).toHaveLength(1);
  });
});
