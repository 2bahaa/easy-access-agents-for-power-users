import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ChatItem } from "../lib/transcript";
import { AgentChat, type AgentChatProps } from "./AgentChat";

const ITEMS: ChatItem[] = [
  { kind: "user", id: "u", content: "What is 17.5 * 23 + 4?", runId: "r-1" },
  { kind: "tool", id: "c1", tool: "calculator", args: { expression: "17.5 * 23 + 4" }, status: "completed", result: "406.5", runId: "r-1" },
  { kind: "assistant", id: "a", content: "The answer is **406.5**.", runId: "r-1" },
  { kind: "notice", id: "n", tone: "warning", text: "Stopped: the run timed out.", runId: "r-2" },
];

function setup(props: Partial<AgentChatProps> = {}) {
  const handlers = { onSend: vi.fn(), onCancel: vi.fn(), onSelectRun: vi.fn() };
  render(<AgentChat items={[]} draft={null} running={false} agentName="Math Tutor" {...handlers} {...props} />);
  return handlers;
}

describe("AgentChat", () => {
  it("renders the transcript with inline tool calls and notices", () => {
    setup({ items: ITEMS });
    expect(screen.getByText("What is 17.5 * 23 + 4?")).toBeInTheDocument();
    const chip = screen.getByRole("button", { name: "Calculator tool call, completed" });
    expect(chip).toHaveTextContent("17.5 * 23 + 4");
    expect(chip).toHaveTextContent("406.5");
    expect(screen.getByText("406.5", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("timed out");
  });

  it("selects a run from a tool chip", async () => {
    const { onSelectRun } = setup({ items: ITEMS });
    await userEvent.click(screen.getByRole("button", { name: /Calculator tool call/ }));
    expect(onSelectRun).toHaveBeenCalledWith("r-1");
  });

  it("sends with Enter, keeps Shift+Enter for new lines, and clears the box", async () => {
    const { onSend } = setup();
    const box = screen.getByRole("textbox", { name: "Message Math Tutor" });
    await userEvent.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.type(box, "{Enter}");
    expect(onSend).toHaveBeenCalledWith("line one\nline two");
    expect(box).toHaveValue("");
  });

  it("ignores blank messages", async () => {
    const { onSend } = setup();
    await userEvent.type(screen.getByRole("textbox"), "   {Enter}");
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("shows streaming text and a stop button while running", async () => {
    const { onCancel, onSend } = setup({ items: ITEMS.slice(0, 1), draft: "Partial ans", running: true });
    expect(screen.getByText("Partial ans")).toBeInTheDocument();
    expect(screen.getByLabelText("Streaming")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox"), "next{Enter}");
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("shows a thinking indicator before the first token", () => {
    setup({ items: ITEMS.slice(0, 1), draft: "", running: true });
    expect(screen.getByLabelText("Agent is thinking")).toBeInTheDocument();
  });

  it("offers suggestions in an empty chat", async () => {
    const { onSend } = setup({ suggestions: ["What can you help me with?"] });
    expect(screen.getByText("Chat with Math Tutor")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "What can you help me with?" }));
    expect(onSend).toHaveBeenCalledWith("What can you help me with?");
  });

  it("shows send errors above the composer", () => {
    setup({ error: "A run is already in progress for this conversation" });
    expect(screen.getByRole("alert")).toHaveTextContent("already in progress");
  });
});
