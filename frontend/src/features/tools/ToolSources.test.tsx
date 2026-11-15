import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { tools } from "../../test/fixtures";
import { ME, mockApi, renderApp } from "../../test/render";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };
const SERVER = {
  id: "m-1", name: "Demo", slug: "demo", transport: "http", command: null, args: [], url: "http://127.0.0.1:8080/mcp",
  secret_keys: ["Authorization"], enabled: true, timeout_s: 30, status: "ok", last_error: null, last_checked_at: null,
  tools: [{ name: "add", description: "Add two integers.", input_schema: { type: "object", properties: { a: { type: "integer" } } }, enabled: false }],
};

describe("Tools page: MCP and HTTP tools", () => {
  it("registers an MCP server with write-only headers", async () => {
    let servers: unknown[] = [];
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /tools": tools,
      "GET /mcp-servers": () => servers,
      "GET /custom-tools": [],
      "POST /mcp-servers": () => {
        servers = [{ ...SERVER, tools: [] }];
        return servers[0];
      },
    });
    renderApp("/tools");
    await userEvent.click(await screen.findByRole("button", { name: "Add MCP server" }));
    const form = screen.getByRole("form", { name: "Add MCP server" });
    await userEvent.type(within(form).getByLabelText(/^Name/), "Demo");
    await userEvent.type(within(form).getByLabelText(/^URL/), "http://127.0.0.1:8080/mcp");
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    await userEvent.type(within(form).getByLabelText("Headers name 1"), "Authorization");
    await userEvent.type(within(form).getByLabelText("Headers value 1"), "Bearer secret");
    await userEvent.click(within(form).getByRole("button", { name: "Save server" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path === "/mcp-servers")?.body).toMatchObject({
        name: "Demo",
        slug: "demo",
        transport: "http",
        url: "http://127.0.0.1:8080/mcp",
        headers: { Authorization: "Bearer secret" },
      }),
    );
    expect(await screen.findByText(/secrets: Authorization/)).toBeInTheDocument();
    expect(screen.queryByText(/Bearer secret/)).toBeNull();
  });

  it("discovers tools and enables one", async () => {
    let enabled = false;
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /tools": tools,
      "GET /mcp-servers": () => [{ ...SERVER, tools: [{ ...SERVER.tools[0], enabled }] }],
      "GET /custom-tools": [],
      "POST /mcp-servers/m-1/refresh": { server: SERVER, warnings: [] },
      "PUT /mcp-servers/m-1/tools/add": () => {
        enabled = true;
        return { ...SERVER.tools[0], enabled: true };
      },
    });
    renderApp("/tools");
    await userEvent.click(await screen.findByRole("button", { name: "Discover tools" }));
    expect(await screen.findByText("Found 1 tools")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Tools of Demo" });
    await userEvent.click(within(list).getByRole("switch", { name: "Enable add" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ enabled: true }));
  });

  it("creates a custom HTTP tool with parameters", async () => {
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /tools": tools,
      "GET /mcp-servers": [],
      "GET /custom-tools": [],
      "POST /custom-tools": { id: "t-1", tool_name: "http__weather", slug: "weather", description: "d", method: "GET", url_template: "https://api.example.test/w/{city}", params: [], header_keys: [], timeout_s: 15, enabled: true, updated_at: "" },
    });
    renderApp("/tools");
    await userEvent.click(await screen.findByRole("button", { name: "Add HTTP tool" }));
    const form = screen.getByRole("form", { name: "Add HTTP tool" });
    await userEvent.type(within(form).getByLabelText(/^Slug/), "weather");
    await userEvent.clear(within(form).getByLabelText(/^URL/));
    await userEvent.type(within(form).getByLabelText(/^URL/), "https://api.example.test/w/{{city}");
    await userEvent.type(within(form).getByLabelText(/^Description/), "Current weather");
    await userEvent.click(within(form).getByRole("button", { name: "Add parameter" }));
    await userEvent.type(within(form).getByLabelText("Parameter 1 name"), "city");
    await userEvent.selectOptions(within(form).getByLabelText("Parameter 1 location"), "path");
    await userEvent.click(within(form).getByRole("button", { name: "Save tool" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path === "/custom-tools")?.body).toMatchObject({
        slug: "weather",
        url_template: "https://api.example.test/w/{city}",
        params: [{ name: "city", type: "string", location: "path", required: true }],
      }),
    );
  });

  it("is read-only for non-admins", async () => {
    mockApi({
      "GET /health": HEALTH,
      "GET /auth/me": { ...ME, role: "editor" },
      "GET /tools": tools,
      "GET /mcp-servers": [SERVER],
      "GET /custom-tools": [],
    });
    renderApp("/tools");
    expect(await screen.findByText("Demo")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add MCP server" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Discover tools" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Enable add" })).toBeDisabled();
  });
});
