import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __getAuthStandIn,
  __resetAuthStandIn,
  __resetFollows,
} from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { createBackendGateway } from "./fetch-client";

const BASE_URL = "http://localhost:8000";

async function loginAsAlice() {
  await createBackendGateway(BASE_URL).login({
    email: "alice@example.com",
    password: "password123",
  });
}

function spyOnFetch() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const realFetch = globalThis.fetch;
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (input: Parameters<typeof fetch>[0], init) => {
      calls.push({ url: String(input), init });
      return realFetch(input, init);
    },
  );
  return calls;
}

afterEach(() => {
  __resetAuthStandIn();
  __resetFollows();
  vi.restoreAllMocks();
});

/**
 * P4 follow contract: the adapter rides the REAL backend follow paths
 * (POST/DELETE /users/{username}/follow, 200 {username,following}) —
 * never the guessed POST /follow. The MSW mirror emits backend-exact
 * envelopes, so these tests prove real-vs-mock parity.
 */
describe("follow contract (P4 real paths)", () => {
  it("follow POSTs /users/{username}/follow with no body and maps the exact {username,following} envelope", async () => {
    await loginAsAlice();
    const calls = spyOnFetch();

    const state = await createBackendGateway(BASE_URL).setFollow({
      username: "bob",
      following: true,
    });

    expect(state).toEqual({ username: "bob", following: true });
    const posts = calls.filter(
      (call) =>
        new URL(call.url).pathname === "/users/bob/follow" &&
        call.init?.method === "POST",
    );
    expect(posts).toHaveLength(1);
    expect(posts[0]?.init?.credentials).toBe("include");
    expect(
      new Headers(posts[0]?.init?.headers).get("authorization"),
    ).toBeNull();
    // The backend takes intent from the method: no request body.
    expect(posts[0]?.init?.body).toBeUndefined();
  });

  it("unfollow DELETEs /users/{username}/follow and maps the exact envelope", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    await gateway.setFollow({ username: "bob", following: true });
    const calls = spyOnFetch();

    const state = await gateway.setFollow({
      username: "bob",
      following: false,
    });

    expect(state).toEqual({ username: "bob", following: false });
    const deletes = calls.filter(
      (call) =>
        new URL(call.url).pathname === "/users/bob/follow" &&
        call.init?.method === "DELETE",
    );
    expect(deletes).toHaveLength(1);
    expect(deletes[0]?.init?.credentials).toBe("include");
  });

  it("never touches the guessed POST /follow path", async () => {
    await loginAsAlice();
    const calls = spyOnFetch();
    const gateway = createBackendGateway(BASE_URL);

    await gateway.setFollow({ username: "bob", following: true });
    await gateway.setFollow({ username: "bob", following: false });

    expect(
      calls.filter((call) => new URL(call.url).pathname === "/follow"),
    ).toHaveLength(0);
  });

  it("unknown target rejects 404 not_found without ending the session", async () => {
    await loginAsAlice();
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await expect(
      gateway.setFollow({ username: "ghost-nobody", following: true }),
    ).rejects.toMatchObject({ status: 404, code: "not_found" });
    await expect(
      gateway.setFollow({ username: "ghost-nobody", following: false }),
    ).rejects.toMatchObject({ status: 404, code: "not_found" });

    // 404 is not 401: the session survives centrally.
    expect(onSessionEnd).not.toHaveBeenCalled();
    expect(__getAuthStandIn()).not.toBeNull();
  });

  it("self-follow rejects 422 validation_error without ending the session", async () => {
    await loginAsAlice();
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await expect(
      gateway.setFollow({ username: "alice", following: true }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      fields: { username: "self_follow" },
    });

    expect(onSessionEnd).not.toHaveBeenCalled();
    expect(__getAuthStandIn()).not.toBeNull();
  });

  it("logged-out follow 401 keeps the central session-end wiring", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await expect(
      gateway.setFollow({ username: "bob", following: true }),
    ).rejects.toMatchObject({ status: 401, code: "unauthenticated" });
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
  });

  it("extra keys on the follow envelope reject 500 (drift detection)", async () => {
    // The backend forbids extras, so a three-key envelope means drift.
    server.use(
      http.post("*/users/bob/follow", () =>
        HttpResponse.json({
          username: "bob",
          following: true,
          followersCount: 99,
        }),
      ),
    );
    await loginAsAlice();

    await expect(
      createBackendGateway(BASE_URL).setFollow({
        username: "bob",
        following: true,
      }),
    ).rejects.toMatchObject({ status: 500 });
  });
});
