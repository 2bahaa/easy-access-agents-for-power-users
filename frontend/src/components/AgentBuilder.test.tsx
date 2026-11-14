import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { emptyAgentForm, fromAgent } from "../lib/agentForm";
import { agent, models, skills, tools } from "../test/fixtures";
import { AgentBuilder, type AgentBuilderProps } from "./AgentBuilder";

function setup(overrides: Partial<AgentBuilderProps> = {}) {
  const onSubmit = vi.fn();
  render(
    <AgentBuilder
      initialValues={emptyAgentForm()}
      isNew
      models={models}
      skills={skills}
      tools={tools}
      onSubmit={onSubmit}
      {...overrides}
    />,
  );
  return { onSubmit };
}

describe("AgentBuilder", () => {
  it("shows validation errors and does not submit an incomplete form", async () => {
    const { onSubmit } = setup();
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Give your agent a name.")).toBeInTheDocument();
    expect(screen.getByText("Choose a model.")).toBeInTheDocument();
    expect(screen.getByText(/Please fix 2 fields/)).toBeInTheDocument();
  });

  it("clears errors live after the first submit attempt", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    await userEvent.type(screen.getByLabelText(/^Name/), "Bot");
    expect(screen.queryByText("Give your agent a name.")).not.toBeInTheDocument();
  });

  it("submits a complete configuration", async () => {
    const { onSubmit } = setup();
    await userEvent.type(screen.getByLabelText(/^Name/), "Math helper");
    await userEvent.click(screen.getByRole("radio", { name: /qwen3:4b/ }));
    await userEvent.click(screen.getByRole("button", { name: "Attach Cite sources" }));
    await userEvent.click(screen.getByRole("switch", { name: "Enable Calculator" }));
    await userEvent.selectOptions(screen.getByLabelText("Context window"), "8192");
    const maxCalls = screen.getByLabelText("Max tool calls");
    await userEvent.clear(maxCalls);
    await userEvent.type(maxCalls, "4");

    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Math helper",
        model: "qwen3:4b",
        provider: "ollama",
        skill_ids: ["s-cite"],
        tools: [{ name: "calculator", config: {} }],
        // qwen3:4b is a thinking model: selecting it turned thinking on and raised the timeout.
        model_params: { num_ctx: 8192, think: true },
        max_tool_calls: 4,
        run_timeout_s: 300,
      }),
    );
  });

  it("adjusts settings when a model is chosen, explains why, and can undo", async () => {
    const { onSubmit } = setup({
      initialValues: { ...emptyAgentForm(), name: "Bot", tools: [{ name: "calculator", config: {} }] },
    });
    await userEvent.click(screen.getByRole("radio", { name: /qwen3:4b/ }));
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Settings adjusted for qwen3:4b");
    expect(notice).toHaveTextContent("Thinking: On");
    expect(notice).toHaveTextContent("Run timeout: 300 s");
    expect(screen.getByLabelText("Thinking")).toHaveValue("on");
    expect(screen.getByLabelText("Run timeout (s)")).toHaveValue(300);

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.queryByText(/Settings adjusted/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Run timeout (s)")).toHaveValue(120);
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ model: "qwen3:4b", model_params: {}, run_timeout_s: 120 }),
    );
  });

  it("removes tools when switching to a model without tool support", async () => {
    setup({
      initialValues: { ...emptyAgentForm(), name: "Bot", model: "qwen3:4b", tools: [{ name: "calculator", config: {} }] },
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument(); // nothing changes on load
    await userEvent.click(screen.getByRole("radio", { name: /gemma:2b/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Tools: removed");
    expect(screen.getByRole("switch", { name: "Enable Calculator" })).toHaveAttribute("aria-checked", "false");
  });

  it("prevents enabling tools on a model without tool support", async () => {
    const { onSubmit } = setup({
      initialValues: { ...emptyAgentForm(), name: "Bot", model: "gemma:2b" },
    });
    expect(screen.getByText(/gemma:2b does not support tool calling/)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Enable Calculator" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ model: "gemma:2b", tools: [] }));
  });

  it("tracks unsaved changes for an existing agent", async () => {
    setup({ initialValues: fromAgent(agent), isNew: false, submitLabel: "Save changes" });
    expect(screen.getByText("All changes saved")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Description/), "!");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("shows server errors, including per-field messages", () => {
    setup({
      serverError: "Model 'gemma:2b' does not support tool calling",
      serverFieldErrors: { name: "String should have at most 100 characters" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("does not support tool calling");
    expect(screen.getByText("String should have at most 100 characters")).toBeInTheDocument();
  });

  it("resets temperature to the model default", async () => {
    const { onSubmit } = setup({ initialValues: { ...fromAgent(agent), temperature: 0.3 } });
    await userEvent.click(screen.getByRole("button", { name: "Reset temperature to model default" }));
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    expect(onSubmit.mock.calls[0]![0].model_params).toEqual({ num_ctx: 8192 });
  });
});
