import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ToolPicker } from "../../components/ToolPicker";
import { mockApi, renderApp } from "../../test/render";

const HEALTH = { status: "ok", database: "ok", ollama: "ok" };
const OLLAMA = {
  name: "ollama", id: null, label: "Ollama (server)", kind: "ollama", builtin: true, base_url: null,
  has_secret: false, secret_hint: null, available: true, status: "ok", last_error: null, last_checked_at: null,
};
const COLLECTION = {
  id: "k-1", name: "Manuals", description: "", embedding_provider: "ollama", embedding_connection_id: null,
  embedding_model: "nomic-embed-text", dims: 768, chunk_size: 900, chunk_overlap: 150, document_count: 1, chunk_count: 3, created_at: "",
};
const DOC = { id: "d-1", collection_id: "k-1", title: "manual.txt", mime: "text/plain", size_bytes: 1200, status: "ready", error: null, chunk_count: 3, created_at: new Date().toISOString() };

describe("Knowledge page", () => {
  it("creates a collection with an embedding model", async () => {
    let collections: unknown[] = [];
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /knowledge/collections": () => collections,
      "GET /providers": [OLLAMA],
      "POST /knowledge/collections": () => {
        collections = [{ ...COLLECTION, document_count: 0, chunk_count: 0 }];
        return collections[0];
      },
      "GET /knowledge/collections/k-1/documents": [],
    });
    renderApp("/knowledge");
    await userEvent.click(await screen.findByRole("button", { name: "New collection" }));
    const form = screen.getByRole("form", { name: "New collection" });
    await userEvent.type(within(form).getByLabelText("Name"), "Manuals");
    await userEvent.click(within(form).getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path === "/knowledge/collections")?.body).toMatchObject({
        name: "Manuals",
        embedding_model: "nomic-embed-text",
        embedding_provider: "ollama",
        embedding_connection_id: null,
      }),
    );
    expect(await screen.findByText(/No documents yet/)).toBeInTheDocument();
  });

  it("uploads a document as the raw body and searches with citations", async () => {
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /knowledge/collections": [COLLECTION],
      "GET /knowledge/collections/k-1/documents": [DOC],
      "POST /knowledge/collections/k-1/documents?filename=notes.md": { ...DOC, id: "d-2", title: "notes.md", status: "queued" },
      "POST /knowledge/search": [
        { document_id: "d-1", document_title: "manual.txt", collection_id: "k-1", chunk: 1, page: null, text: "The warranty is ten years.", score: 0.03 },
      ],
    });
    renderApp("/knowledge");
    expect(await screen.findByText("manual.txt")).toBeInTheDocument();
    const file = new File(["# Notes"], "notes.md", { type: "text/markdown" });
    fireEvent.change(screen.getByLabelText("Upload document"), { target: { files: [file] } });
    await waitFor(() => expect(calls.some((c) => c.path === "/knowledge/collections/k-1/documents?filename=notes.md")).toBe(true));

    await userEvent.type(screen.getByLabelText("Search query"), "warranty");
    await userEvent.click(
      within(screen.getByRole("form", { name: "Search collection" })).getByRole("button", { name: "Search" }),
    );
    const results = await screen.findByRole("list", { name: "Search results" });
    expect(within(results).getByText(/\[1\] manual.txt, chunk 2/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/knowledge/search")?.body).toEqual({ collection_ids: ["k-1"], query: "warranty", top_k: 5 });
  });

  it("lists and forgets agent memories", async () => {
    const { calls } = mockApi({
      "GET /health": HEALTH,
      "GET /knowledge/collections": [],
      "GET /agents": [{ id: "a-1", name: "Helper", description: "", provider: "ollama", model: "m", updated_at: "" }],
      "GET /agents/a-1/memories": [{ id: "mem-1", agent_id: "a-1", content: "Likes teal", run_id: null, created_at: new Date().toISOString() }],
      "DELETE /memories/mem-1": new Response(null, { status: 204 }),
    });
    renderApp("/knowledge");
    await userEvent.click(await screen.findByRole("tab", { name: /Agent memory/ }));
    expect(await screen.findByText("Likes teal")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Forget this memory" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/memories/mem-1")).toBe(true));
  });
});

describe("ToolPicker knowledge collections", () => {
  it("writes the selected collection ids into the tool config", async () => {
    const onChange = vi.fn();
    const tool = {
      name: "knowledge__search", description: "Search", args_schema: { type: "object", properties: {} },
      config_schema: { type: "object", properties: {} }, timeout_s: 30, source: "knowledge" as const,
    };
    render(
      <ToolPicker
        tools={[tool]}
        value={[{ name: "knowledge__search", config: {} }]}
        onChange={onChange}
        collections={[{ id: "k-1", name: "Manuals" }]}
      />,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "Manuals" }));
    expect(onChange).toHaveBeenLastCalledWith([{ name: "knowledge__search", config: { collection_ids: ["k-1"] } }]);
  });
});
