import { authFetch, refreshSession, session } from "./session";

function json(status: number, body: unknown = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("auth session", () => {
  beforeEach(() => {
    session.setToken(null);
    session.setWorkspaceId(null);
  });

  it("attaches the bearer token and workspace header", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => json(200));
    vi.stubGlobal("fetch", fetchMock);
    session.setToken("tok");
    session.setWorkspaceId("w-9");
    await authFetch("/api/agents");
    const init = fetchMock.mock.calls[0]![1]!;
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok");
    expect(headers.get("X-Workspace-Id")).toBe("w-9");
    expect(localStorage.getItem("eaa.workspace")).toBe("w-9");
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401))
      .mockResolvedValueOnce(json(200, { access_token: "fresh" }))
      .mockResolvedValueOnce(json(200, [{ id: "a" }]));
    vi.stubGlobal("fetch", fetchMock);
    session.setToken("stale");
    const res = await authFetch("/api/agents");
    expect(res.status).toBe(200);
    expect(fetchMock.mock.calls[1]![0]).toBe("/api/auth/refresh");
    expect(new Headers((fetchMock.mock.calls[2]![1] as RequestInit).headers).get("Authorization")).toBe("Bearer fresh");
  });

  it("reports expiry when the refresh fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(401)).mockResolvedValueOnce(json(401)));
    const expired = vi.fn();
    const off = session.onExpired(expired);
    const res = await authFetch("/api/agents");
    expect(res.status).toBe(401);
    expect(expired).toHaveBeenCalledOnce();
    expect(session.getToken()).toBeNull();
    off();
  });

  it("does not refresh on credential endpoints", async () => {
    const fetchMock = vi.fn(async () => json(401, { detail: "Invalid email or password" }));
    vi.stubGlobal("fetch", fetchMock);
    const res = await authFetch("/api/auth/login", { method: "POST" });
    expect(res.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("shares one refresh request between concurrent callers", async () => {
    const fetchMock = vi.fn(async () => json(200, { access_token: "t" }));
    vi.stubGlobal("fetch", fetchMock);
    const results = await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
    expect(results).toEqual([true, true, true]);
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
