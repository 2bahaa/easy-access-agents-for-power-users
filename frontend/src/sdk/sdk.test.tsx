import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CALCULATOR_RUN } from "../test/stream";
import { sseResponse, toSSE } from "../test/stream";
import * as sdk from "./index";

describe("SDK surface", () => {
  it("exports the prop-driven components and state helpers", () => {
    for (const name of [
      "AgentChat",
      "AgentRunTimeline",
      "AgentBuilder",
      "ApprovalCard",
      "ModelPicker",
      "ToolPicker",
      "SkillSelector",
      "WorkflowEditor",
      "UsageChart",
      "Markdown",
    ]) {
      expect(typeof (sdk as Record<string, unknown>)[name]).toBe("function");
    }
    expect(typeof sdk.runReducer).toBe("function");
    expect(typeof sdk.createAgentClient).toBe("function");
  });

  it("renders a chat and its timeline from an event stream with no app context", async () => {
    const state = CALCULATOR_RUN.reduce(sdk.runReducer, sdk.initialRunState);
    const onSend = vi.fn();
    render(
      <>
        <sdk.AgentChat
          items={sdk.liveTranscript(state, "What is 6*7?")}
          draft={null}
          running={false}
          onSend={onSend}
          onCancel={vi.fn()}
          agentName="Calc"
        />
        <sdk.AgentRunTimeline items={state.items} status={state.status} />
      </>,
    );
    expect(
      screen.getByRole("list", { name: "Run timeline" }),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox"), "hello{Enter}");
    expect(onSend).toHaveBeenCalledWith("hello");
  });
});

describe("createAgentClient", () => {
  it("sends the token and workspace, streams events and surfaces API errors", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      if (url.endsWith("/messages")) return sseResponse(toSSE(CALCULATOR_RUN));
      if (url.endsWith("/conversations"))
        return new Response(JSON.stringify({ id: "c-1" }), { status: 201 });
      return new Response(JSON.stringify({ detail: "Approval not found" }), {
        status: 404,
      });
    });
    const client = sdk.createAgentClient({
      baseUrl: "https://agents.test/api/",
      getToken: () => "eaa_secret",
      workspaceId: "ws-1",
      fetch: fetchMock as unknown as typeof fetch,
    });

    const conv = await client.createConversation("a-1");
    expect(conv.id).toBe("c-1");
    const headers = new Headers(calls[0]!.init.headers);
    expect(calls[0]!.url).toBe("https://agents.test/api/conversations");
    expect(headers.get("Authorization")).toBe("Bearer eaa_secret");
    expect(headers.get("X-Workspace-Id")).toBe("ws-1");
    expect(JSON.parse(String(calls[0]!.init.body))).toEqual({
      agent_id: "a-1",
    });

    const types: string[] = [];
    for await (const event of client.sendMessage("c-1", "6*7?"))
      types.push(event.type);
    expect(types).toEqual(CALCULATOR_RUN.map((e) => e.type));

    await expect(client.decideApproval("x", "approve")).rejects.toThrow(
      "404: Approval not found",
    );
    expect(calls.at(-1)!.url).toBe(
      "https://agents.test/api/approvals/x/decide",
    );
    expect(JSON.parse(String(calls.at(-1)!.init.body))).toEqual({
      decision: "approve",
      args: null,
      note: "",
    });
  });
});
