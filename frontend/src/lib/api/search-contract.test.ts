import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpResponse, http } from "msw";
import { __resetAuthStandIn } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { createBackendGateway } from "./fetch-client";
import { ApiError } from "./port";

const BASE_URL = "http://localhost:8000";

beforeEach(() => {
  __resetAuthStandIn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function loginAsAlice() {
  await createBackendGateway(BASE_URL).login({
    email: "alice@example.com",
    password: "password123",
  });
}

describe("searchUsers contract", () => {
  it("GETs /users/search?q= and maps exact public identity rows", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();

    const seen: Array<{ url: string; init?: RequestInit }> = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        seen.push({ url: String(input), init });
        return realFetch(input, init);
      },
    );

    const items = await gateway.searchUsers(" bo ");

    expect(items).toEqual([
      { id: "u-bob", username: "bob", displayName: "Bob" },
    ]);
    const call = seen.find((entry) => entry.url.includes("/users/search"));
    expect(call).toBeDefined();
    const url = new URL(call?.url ?? "");
    expect(url.pathname).toBe("/users/search");
    expect(url.searchParams.get("q")).toBe(" bo ");
    expect(call?.init?.credentials).toBe("include");
    expect(new Headers(call?.init?.headers).get("authorization")).toBeNull();
  });

  it("rejects missing, empty, duplicate, and too-long q with 422", async () => {
    await loginAsAlice();

    const cases = [
      "/users/search",
      "/users/search?q=",
      "/users/search?q=a&q=b",
      `/users/search?q=${"x".repeat(51)}`,
    ];
    for (const path of cases) {
      const response = await fetch(`${BASE_URL}${path}`, {
        credentials: "include",
      });
      expect(response.status, path).toBe(422);
      await expect(response.json(), path).resolves.toEqual({
        error: { code: "validation_error", fields: { q: "invalid" } },
      });
    }
  });

  it("401 ends the session for logged-out search", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await expect(gateway.searchUsers("alice")).rejects.toMatchObject({
      status: 401,
      code: "unauthenticated",
    });
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
  });

  it("rejects search envelope drift with 500", async () => {
    await loginAsAlice();
    server.use(
      http.get("*/users/search", () =>
        HttpResponse.json({
          items: [
            {
              id: "u-bob",
              username: "bob",
              display_name: "Bob",
              email: "bob@example.com",
            },
          ],
        }),
      ),
    );
    const gateway = createBackendGateway(BASE_URL);

    await expect(gateway.searchUsers("bob")).rejects.toBeInstanceOf(ApiError);
    await expect(gateway.searchUsers("bob")).rejects.toMatchObject({
      status: 500,
    });
  });
});
