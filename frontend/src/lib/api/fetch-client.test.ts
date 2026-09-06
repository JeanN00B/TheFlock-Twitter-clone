import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __getAuthStandIn,
  __resetAuthStandIn,
  __resetRegistration,
} from "@/mocks/handlers";
import { createBackendGateway } from "./fetch-client";
import { ApiError } from "./port";

const BASE_URL = "http://localhost:8000";

afterEach(() => {
  __resetAuthStandIn();
  __resetRegistration();
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

  describe("BackendGateway registration seam", () => {
    it("registers with the strict backend shape and maps a 201 response", async () => {
      const seen: Array<RequestInit | undefined> = [];
      const realFetch = globalThis.fetch;
      vi.spyOn(globalThis, "fetch").mockImplementation(
        async (...args: Parameters<typeof fetch>) => {
          seen.push(args[1]);
          return realFetch(...args);
        },
      );
      const onSessionEnd = vi.fn();

      const result = await createBackendGateway(BASE_URL, {
        onSessionEnd,
      }).register({
        email: "new@example.com",
        username: "NewUser",
        displayName: "New User",
        password: "password123",
      });

      expect(result).toMatchObject({
        id: expect.stringMatching(
          /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
        ),
        username: "newuser",
        displayName: "New User",
        email: "new@example.com",
        createdAt: expect.stringMatching(/Z$/),
        updatedAt: expect.stringMatching(/Z$/),
      });
      expect(Object.keys(result)).toEqual([
        "id",
        "username",
        "displayName",
        "email",
        "createdAt",
        "updatedAt",
      ]);
      expect(seen).toHaveLength(1);
      expect(seen[0]?.credentials).toBe("include");
      expect(new Headers(seen[0]?.headers).get("authorization")).toBeNull();
      expect(JSON.parse(String(seen[0]?.body))).toEqual({
        email: "new@example.com",
        username: "NewUser",
        display_name: "New User",
        password: "password123",
      });
      expect(onSessionEnd).not.toHaveBeenCalled();
      expect(__getAuthStandIn()).toBeNull();
    });

    it("preserves nested validation errors without ending the session", async () => {
      const onSessionEnd = vi.fn();
      const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

      await expect(
        gateway.register({
          email: "not-an-email",
          username: "newuser",
          displayName: "New User",
          password: "password123",
        }),
      ).rejects.toMatchObject({
        status: 422,
        code: "validation_error",
        fields: { email: "invalid" },
      });
      expect(onSessionEnd).not.toHaveBeenCalled();
      expect(__getAuthStandIn()).toBeNull();
    });

    it("returns every invalid registration field for a combined invalid payload", async () => {
      const onSessionEnd = vi.fn();
      const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

      await expect(
        gateway.register({
          email: "not-an-email",
          username: "@alice",
          displayName: "   ",
          password: "short",
        }),
      ).rejects.toMatchObject({
        status: 422,
        code: "validation_error",
        fields: {
          email: "invalid",
          username: "invalid",
          display_name: "invalid",
          password: "invalid",
        },
      });
      expect(onSessionEnd).not.toHaveBeenCalled();
      expect(__getAuthStandIn()).toBeNull();
    });

    it("preserves both nested conflict fields without an auth stand-in", async () => {
      const onSessionEnd = vi.fn();
      const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

      await expect(
        gateway.register({
          email: "alice@example.com",
          username: "alice",
          displayName: "Alice",
          password: "password123",
        }),
      ).rejects.toMatchObject({
        status: 409,
        code: "conflict",
        fields: { email: "already_exists", username: "already_exists" },
      });
      expect(onSessionEnd).not.toHaveBeenCalled();
      expect(__getAuthStandIn()).toBeNull();
    });

    it("keeps registration state so a successful duplicate conflicts", async () => {
      const gateway = createBackendGateway(BASE_URL);
      const input = {
        email: "stateful@example.com",
        username: "StatefulUser",
        displayName: "Stateful User",
        password: "password123",
      };

      await gateway.register(input);
      await expect(gateway.register(input)).rejects.toMatchObject({
        status: 409,
        code: "conflict",
        fields: { email: "already_exists", username: "already_exists" },
      });
      expect(__getAuthStandIn()).toBeNull();
    });
  });
});
