import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SkillEditor } from "./SkillEditor";

const EMPTY = { slug: "", name: "", description: "", content_md: "" };

describe("SkillEditor", () => {
  it("derives the slug from the name for new skills until edited", async () => {
    const onSubmit = vi.fn();
    render(<SkillEditor initialValues={EMPTY} isNew onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText(/^Name/), "Cite Sources!");
    expect(screen.getByLabelText(/^Slug/)).toHaveValue("cite-sources");

    await userEvent.type(screen.getByLabelText(/^Instructions/), "Always cite.");
    await userEvent.click(screen.getByRole("button", { name: "Create skill" }));
    expect(onSubmit).toHaveBeenCalledWith({
      slug: "cite-sources",
      name: "Cite Sources!",
      description: "",
      content_md: "Always cite.",
    });
  });

  it("validates required fields and slug format", async () => {
    const onSubmit = vi.fn();
    render(
      <SkillEditor
        initialValues={{ ...EMPTY, name: "X", slug: "Bad Slug" }}
        onSubmit={onSubmit}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/lowercase letters, numbers/)).toBeInTheDocument();
    expect(screen.getByText(/Write the instructions/)).toBeInTheDocument();
  });

  it("does not overwrite the slug of an existing skill when renaming", async () => {
    render(
      <SkillEditor
        initialValues={{ slug: "keep-me", name: "Old", description: "", content_md: "x" }}
        onSubmit={() => {}}
      />,
    );
    await userEvent.type(screen.getByLabelText(/^Name/), " name");
    expect(screen.getByLabelText(/^Slug/)).toHaveValue("keep-me");
  });
});
