import { ApiError, api, errorMessage, request } from "./client";

function respond(status: number, body?: unknown, statusText = "") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      body === undefined
        ? new Response(null, { status, statusText })
        : new Response(typeof body === "string" ? body : JSON.stringify(body), { status, statusText }),
    ),
  );
}

describe("api client", () => {
  it("returns parsed JSON and sends JSON bodies", async () => {
    respond(201, { id: "x" });
    const result = await api.createSkill({ slug: "a", name: "A", description: "", content_md: "x" });
    expect(result).toEqual({ id: "x" });
    const [url, init] = vi.mocked(fetch).mock.calls[0]!;
    expect(url).toBe("/api/skills");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toMatchObject({ slug: "a" });
  });

  it("handles 204 No Content", async () => {
    respond(204);
    await expect(api.deleteAgent("a-1")).resolves.toBeUndefined();
  });

  it("raises ApiError with the problem detail", async () => {
    respond(409, { title: "Conflict", status: 409, detail: "Skill slug 'a' already exists" });
    const err = await request("/skills").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect(errorMessage(err)).toBe("Skill slug 'a' already exists");
  });

  it("exposes request validation errors per field", async () => {
    respond(422, {
      title: "Validation error",
      detail: "Request validation failed",
      errors: [{ loc: ["body", "name"], msg: "String should have at least 1 character", type: "x" }],
    });
    const err = (await request("/agents").catch((e: unknown) => e)) as ApiError;
    expect(err.fieldErrors()).toEqual({ name: "String should have at least 1 character" });
    expect(errorMessage(err)).toBe("name: String should have at least 1 character");
  });

  it("copes with non-JSON error bodies", async () => {
    respond(502, "<html>Bad gateway</html>", "Bad Gateway");
    const err = (await request("/health").catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(502);
    expect(err.detail).toBe("Bad Gateway");
  });

  it("explains network failures", () => {
    expect(errorMessage(new TypeError("Failed to fetch"))).toMatch(/Cannot reach the backend/);
  });
});
