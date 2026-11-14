import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import type { ToolSelection } from "../api/types";
import { tools } from "../test/fixtures";
import { ToolPicker } from "./ToolPicker";

function Harness({
  initial = [],
  onChange,
  disabledReason,
}: {
  initial?: ToolSelection[];
  onChange?: (v: ToolSelection[]) => void;
  disabledReason?: string;
}) {
  const [value, setValue] = useState(initial);
  return (
    <ToolPicker
      tools={tools}
      value={value}
      disabledReason={disabledReason}
      onChange={(v) => {
        setValue(v);
        onChange?.(v);
      }}
    />
  );
}

describe("ToolPicker", () => {
  it("lists tools with readable names, descriptions and parameters", () => {
    render(<Harness />);
    expect(screen.getByText("Calculator")).toBeInTheDocument();
    expect(screen.getByText("File Reader")).toBeInTheDocument();
    expect(screen.getByText("(expression)")).toBeInTheDocument();
    expect(screen.getByText("5s timeout")).toBeInTheDocument();
  });

  it("enables a tool with its schema defaults and shows its config", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    expect(screen.queryByLabelText("Subfolder")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("switch", { name: "Enable File Reader" }));
    expect(onChange).toHaveBeenLastCalledWith([{ name: "file_reader", config: { subdir: "" } }]);

    const subfolder = screen.getByLabelText("Subfolder");
    expect(subfolder).toHaveAttribute("placeholder", "e.g. notes");
    await userEvent.type(subfolder, "docs");
    expect(onChange).toHaveBeenLastCalledWith([{ name: "file_reader", config: { subdir: "docs" } }]);
  });

  it("disables a tool again", async () => {
    const onChange = vi.fn();
    render(<Harness initial={[{ name: "calculator", config: {} }]} onChange={onChange} />);
    const toggle = screen.getByRole("switch", { name: "Enable Calculator" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    await userEvent.click(toggle);
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("blocks enabling tools when the model cannot call tools, but allows disabling", async () => {
    render(
      <Harness
        initial={[{ name: "calculator", config: {} }]}
        disabledReason="gemma:2b does not support tool calling."
      />,
    );
    expect(screen.getByText(/does not support tool calling/)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Enable File Reader" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Enable Calculator" })).toBeEnabled();
  });
});
