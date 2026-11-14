import { render, screen } from "@testing-library/react";

import { Markdown } from "./Markdown";

describe("Markdown", () => {
  it("renders common formatting", () => {
    const { container } = render(
      <Markdown
        text={"# Title\n\nSome **bold**, *italic* and `code`.\n\n- one\n- two\n\n1. first\n2. second\n\n> quoted"}
      />,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Title");
    expect(container.querySelector("strong")).toHaveTextContent("bold");
    expect(container.querySelector("em")).toHaveTextContent("italic");
    expect(container.querySelector("code")).toHaveTextContent("code");
    expect(container.querySelector("ul")?.children).toHaveLength(2);
    expect(container.querySelector("ol")?.children).toHaveLength(2);
    expect(container.querySelector("blockquote")).toHaveTextContent("quoted");
  });

  it("renders fenced code blocks verbatim, even while still streaming", () => {
    const { container } = render(<Markdown text={"```python\nprint('**not bold**')\n"} />);
    const pre = container.querySelector("pre");
    expect(pre).toHaveTextContent("python");
    expect(pre).toHaveTextContent("print('**not bold**')");
    expect(container.querySelector("strong")).toBeNull();
  });

  it("never injects HTML from model output", () => {
    const { container } = render(<Markdown text={'<img src=x onerror="alert(1)"> <script>alert(1)</script>'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container).toHaveTextContent("<img src=x");
  });

  it("only links http(s) URLs and opens them safely", () => {
    render(<Markdown text={"[docs](https://example.com) and [bad](javascript:alert(1))"} />);
    const link = screen.getByRole("link", { name: "docs" });
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveAttribute("rel", "noreferrer noopener");
    expect(screen.queryByRole("link", { name: "bad" })).toBeNull();
  });
});
