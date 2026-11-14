import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { skills } from "../test/fixtures";
import { SkillSelector } from "./SkillSelector";

function Harness({ initial = [] as string[] }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <SkillSelector skills={skills} value={value} onChange={setValue} />
      <output data-testid="value">{value.join(",")}</output>
    </>
  );
}

const value = () => screen.getByTestId("value").textContent;

describe("SkillSelector", () => {
  it("attaches skills in click order", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Attach Cite sources" }));
    await userEvent.click(screen.getByRole("button", { name: "Attach Concise answers" }));
    expect(value()).toBe("s-cite,s-concise");
    const attached = within(screen.getByRole("list", { name: "Attached skills" }));
    expect(attached.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("Cite sources"),
      expect.stringContaining("Concise answers"),
    ]);
  });

  it("reorders and removes attached skills", async () => {
    render(<Harness initial={["s-concise", "s-cite", "s-steps"]} />);
    expect(screen.getByRole("button", { name: "Move Concise answers up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move Step by step down" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Move Step by step up" }));
    expect(value()).toBe("s-concise,s-steps,s-cite");
    await userEvent.click(screen.getByRole("button", { name: "Move Concise answers down" }));
    expect(value()).toBe("s-steps,s-concise,s-cite");
    await userEvent.click(screen.getByRole("button", { name: "Remove Concise answers" }));
    expect(value()).toBe("s-steps,s-cite");
  });

  it("filters the library by search text", async () => {
    render(<Harness />);
    await userEvent.type(screen.getByRole("textbox", { name: "Search skills" }), "work");
    const library = within(screen.getByRole("list", { name: "Available skills" }));
    expect(library.getByText("Step by step")).toBeInTheDocument();
    expect(library.queryByText("Cite sources")).not.toBeInTheDocument();
  });

  it("shows an empty state with an action when there are no skills", () => {
    render(<SkillSelector skills={[]} value={[]} onChange={() => {}} emptyAction={<a href="/x">Create</a>} />);
    expect(screen.getByText(/library is empty/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create" })).toBeInTheDocument();
  });
});
