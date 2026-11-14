import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { models } from "../test/fixtures";
import { ModelPicker } from "./ModelPicker";

describe("ModelPicker", () => {
  it("shows capability badges and selects a model", async () => {
    const onChange = vi.fn();
    render(<ModelPicker models={models} value="qwen3:4b" onChange={onChange} />);

    const qwen = screen.getByRole("radio", { name: /qwen3:4b/ });
    expect(qwen).toHaveAttribute("aria-checked", "true");
    expect(within(qwen).getByText("Tools")).toBeInTheDocument();
    expect(within(qwen).getByText("Thinking")).toBeInTheDocument();
    expect(within(qwen).getByText("2.4 GB")).toBeInTheDocument();

    const gemma = screen.getByRole("radio", { name: /gemma:2b/ });
    expect(within(gemma).getByText("No tools")).toBeInTheDocument();
    await userEvent.click(gemma);
    expect(onChange).toHaveBeenCalledWith("gemma:2b");
  });

  it("warns when the configured model is not installed", () => {
    render(<ModelPicker models={models} value="llama3:70b" onChange={() => {}} />);
    expect(screen.getByText(/is not installed in Ollama/)).toBeInTheDocument();
  });

  it("falls back to a text input when the model list is unavailable", async () => {
    const onChange = vi.fn();
    render(
      <ModelPicker models={undefined} value="" onChange={onChange} unavailableMessage="Ollama is not reachable" />,
    );
    expect(screen.getByText(/Ollama is not reachable/)).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "Model name" }), "q");
    expect(onChange).toHaveBeenCalledWith("q");
  });

  it("explains how to install a model when none exist", () => {
    render(<ModelPicker models={[]} value="" onChange={() => {}} />);
    expect(screen.getByText(/No models installed/)).toBeInTheDocument();
  });
});
