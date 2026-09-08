import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { __resetAuthStandIn } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { createBackendGateway } from "./fetch-client";

const BASE_URL = "http://localhost:8000";
const exactProfile = {
  id: "u-bob",
  username: "bob",
  display_name: "Bob",
  followers_count: 2,
  following_count: 3,
  followed_by_actor: true,
};
const legacyProfile = {
  user: { id: "u-bob", username: "bob", display_name: "Bob" },
  following: true,
  followers_count: 2,
  following_count: 3,
};

const profileResponse = (payload: unknown, username = "bob", status = 200) =>
  http.get(`*/users/${username}`, () =>
    HttpResponse.json(payload as Record<string, unknown>, { status }),
  );
const profileWith = (changes: Record<string, unknown>) => ({ ...exactProfile, ...changes });

async function loginAsAlice() {
  await createBackendGateway(BASE_URL).login({
    email: "alice@example.com",
    password: "password123",
  });
}

afterEach(() => {
  __resetAuthStandIn();
  vi.restoreAllMocks();
});

describe("public profile adapter contract (P5)", () => {
  it("gets the exact users route and maps the six snake_case fields", async () => {
    server.use(profileResponse(exactProfile));
    await loginAsAlice();
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        calls.push({ url: String(input), init });
        return realFetch(input, init);
      },
    );

    const profile = await createBackendGateway(BASE_URL).profile("bob");
    expect(profile).toEqual({
      id: "u-bob",
      username: "bob",
      displayName: "Bob",
      followersCount: 2,
      followingCount: 3,
      followedByActor: true,
    });
    const profileCalls = calls.filter(
      (call) => new URL(call.url).pathname === "/users/bob",
    );
    expect(profileCalls).toHaveLength(1);
    expect(profileCalls[0]?.init?.method).toBe("GET");
    expect(profileCalls[0]?.init?.credentials).toBe("include");
    expect(
      new Headers(profileCalls[0]?.init?.headers).get("authorization"),
    ).toBeNull();
    expect(calls.some((call) => call.url.includes("/profile/"))).toBe(false);
  });

  it.each([
    ["missing required field", profileWith({ followers_count: undefined })],
    ["wrong type", profileWith({ following_count: "3" })],
    ["null field", profileWith({ followed_by_actor: null })],
    ["extra field", profileWith({ updated_at: "2024-01-01T00:00:00Z" })],
    ["bio field", profileWith({ bio: "private" })],
    ["avatar field", profileWith({ avatar_url: "https://example.test/avatar" })],
    ["legacy nested profile", legacyProfile],
    ["negative count", profileWith({ followers_count: -1 })],
    ["fractional count", profileWith({ following_count: 1.5 })],
    [
      "camelCase display name",
      profileWith({ display_name: undefined, displayName: "Bob" }),
    ],
    ["camelCase counts", profileWith({ followers_count: undefined, following_count: undefined, followersCount: 2, followingCount: 3 })],
    ["camelCase relationship", profileWith({ followed_by_actor: undefined, followedByActor: true })],
  ] as const)("rejects %s as a local 500 shape error", async (_label, payload) => {
    server.use(profileResponse(payload));
    await loginAsAlice();
    const onSessionEnd = vi.fn();

    await expect(
      createBackendGateway(BASE_URL, { onSessionEnd }).profile("bob"),
    ).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      message: "Unexpected profile shape",
    });
    expect(onSessionEnd).not.toHaveBeenCalled();
  });

  it.each([
    ["unknown", "ghost", { error: { code: "not_found" } }, 404],
    ["invalid", "invalid", { error: { code: "validation_error", fields: { username: "invalid" } } }, 422],
  ] as const)("keeps a %s profile error local", async (_label, username, body, status) => {
    server.use(profileResponse(body, username, status));
    await loginAsAlice();
    const onSessionEnd = vi.fn();

    await expect(
      createBackendGateway(BASE_URL, { onSessionEnd }).profile(username),
    ).rejects.toMatchObject({ status });
    expect(onSessionEnd).not.toHaveBeenCalled();
  });

  it("ends the session centrally for a profile 401", async () => {
    server.use(
      http.get("*/users/bob", () =>
        HttpResponse.json({ error: { code: "unauthenticated" } }, { status: 401 }),
      ),
    );
    const onSessionEnd = vi.fn();

    await expect(
      createBackendGateway(BASE_URL, { onSessionEnd }).profile("bob"),
    ).rejects.toMatchObject({ status: 401, code: "unauthenticated" });
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
  });
});
