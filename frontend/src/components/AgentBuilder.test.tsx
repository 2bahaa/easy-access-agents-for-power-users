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
        model_params: { num_ctx: 8192 },
        max_tool_calls: 4,
        run_timeout_s: 120,
      }),
    );
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
