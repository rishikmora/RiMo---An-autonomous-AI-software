import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, clearToken, getToken, setTokens } from "@/lib/api";

// jsdom provides localStorage; ensure a clean slate each test.
beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

function mockFetchOnce(status: number, body: unknown) {
  return vi.spyOn(global, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("token storage", () => {
  it("stores and clears the access token", () => {
    expect(getToken()).toBeNull();
    setTokens("access-123", "refresh-456");
    expect(getToken()).toBe("access-123");
    clearToken();
    expect(getToken()).toBeNull();
  });
});

describe("api.login", () => {
  it("posts form-encoded credentials and stores the token pair", async () => {
    const spy = mockFetchOnce(200, {
      access_token: "acc",
      refresh_token: "ref",
      token_type: "bearer",
      expires_in: 900,
    });

    await api.login("user@example.com", "secret123");

    expect(spy).toHaveBeenCalledOnce();
    const [url, init] = spy.mock.calls[0];
    expect(String(url)).toContain("/auth/login");
    expect(init?.method).toBe("POST");
    expect(String(init?.headers && (init.headers as Record<string, string>)["Content-Type"]))
      .toContain("x-www-form-urlencoded");
    // Token pair persisted.
    expect(getToken()).toBe("acc");
    expect(window.localStorage.getItem("rimo_refresh")).toBe("ref");
  });

  it("throws ApiError with the server detail on 401", async () => {
    mockFetchOnce(401, { detail: "Incorrect email or password" });
    await expect(api.login("u@e.com", "wrong")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("authenticated requests", () => {
  it("attaches the bearer token", async () => {
    setTokens("my-token", "ref");
    const spy = mockFetchOnce(200, { projects_active: 0 });

    await api.dashboard();

    const [, init] = spy.mock.calls[0];
    const headers = init?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer my-token");
  });

  it("transparently refreshes on a 401 then retries", async () => {
    setTokens("expired", "good-refresh");
    const spy = vi.spyOn(global, "fetch");
    // 1) initial request 401s
    spy.mockResolvedValueOnce(new Response("{}", { status: 401 }));
    // 2) refresh succeeds
    spy.mockResolvedValueOnce(
      new Response(JSON.stringify({ access_token: "new", refresh_token: "new-ref" }), { status: 200 }),
    );
    // 3) retried request succeeds
    spy.mockResolvedValueOnce(
      new Response(JSON.stringify([{ id: "p1" }]), { status: 200 }),
    );

    const projects = await api.projects();

    expect(spy).toHaveBeenCalledTimes(3);
    expect(projects).toEqual([{ id: "p1" }]);
    expect(getToken()).toBe("new"); // rotated access token stored
  });
});
