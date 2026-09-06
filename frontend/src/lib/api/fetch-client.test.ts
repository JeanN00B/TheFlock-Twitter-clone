import { afterEach, describe, expect, it, vi } from "vitest";
import { __getAuthStandIn, __resetAuthStandIn } from "@/mocks/handlers";
import { createBackendGateway } from "./fetch-client";
import { ApiError } from "./port";

const BASE_URL = "http://localhost:8000";

afterEach(() => {
  __resetAuthStandIn();
  vi.restoreAllMocks();
});

describe("BackendGateway auth seam (S1)", () => {
  it("login returns the user over a cookie session, never Authorization", async () => {
    const seen: Array<RequestInit | undefined> = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (...args: Parameters<typeof fetch>) => {
        seen.push(args[1]);
        return realFetch(...args);
      },
    );

    const user = await createBackendGateway(BASE_URL).login({
      username: "alice",
      password: "password123",
    });

    expect(user).toMatchObject({ username: "alice", id: "u-alice" });
    expect(__getAuthStandIn()).toContain("session=");
    expect(seen).toHaveLength(1);
    expect(seen[0]?.credentials).toBe("include");
    expect(new Headers(seen[0]?.headers).get("authorization")).toBeNull();
  });

  it("bad credentials reject with 401 and hold nothing", async () => {
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd: vi.fn() });

    await expect(
      gateway.login({ username: "alice", password: "wrong" }),
    ).rejects.toMatchObject({ status: 401 });
    expect(__getAuthStandIn()).toBeNull();
  });

  it("any 401 ends the session centrally (clear + /login wiring)", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await expect(
      gateway.login({ username: "alice", password: "wrong" }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
  });

  it("logout ends the session via POST /auth/logout", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await gateway.login({ username: "alice", password: "password123" });
    await gateway.logout();

    expect(__getAuthStandIn()).toBeNull();
    expect(onSessionEnd).toHaveBeenCalled();
  });
});
