import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __getAuthStandIn,
  __resetAuthStandIn,
  __resetRegistration,
  __setLoginOriginAllowed,
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
  it("login posts email credentials and succeeds empty over a cookie session, never Authorization", async () => {
    const seen: Array<{ url: string; init?: RequestInit }> = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        seen.push({ url: String(input), init });
        return realFetch(input, init);
      },
    );

    await expect(
      createBackendGateway(BASE_URL).login({
        email: "alice@example.com",
        password: "password123",
      }),
    ).resolves.toBeUndefined();

    // Backend answers 204 empty: exactly {email,password} on the wire
    // (extra keys are forbidden), session lives in the cookie only.
    expect(JSON.parse(String(seen[0]?.init?.body))).toEqual({
      email: "alice@example.com",
      password: "password123",
    });
    expect(__getAuthStandIn()).toContain("flock_session=");
    expect(seen).toHaveLength(1);
    expect(seen[0]?.init?.credentials).toBe("include");
    expect(new Headers(seen[0]?.init?.headers).get("authorization")).toBeNull();
  });

  it("bad credentials reject with 401 invalid_credentials and hold nothing", async () => {
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd: vi.fn() });

    await expect(
      gateway.login({ email: "alice@example.com", password: "wrong" }),
    ).rejects.toMatchObject({ status: 401, code: "invalid_credentials" });
    expect(__getAuthStandIn()).toBeNull();
  });

  it("any 401 ends the session centrally (clear + /login wiring)", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await expect(
      gateway.login({ email: "alice@example.com", password: "wrong" }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
  });

  it("sends only the contract fields, stripping unknown keys", async () => {
    const seen: Array<{ url: string; init?: RequestInit }> = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        seen.push({ url: String(input), init });
        return realFetch(input, init);
      },
    );
    const gateway = createBackendGateway(BASE_URL);

    // The adapter maps explicitly (extra keys are forbidden server-side),
    // so unknown fields never reach the wire.
    await expect(
      gateway.login({
        email: "alice@example.com",
        password: "password123",
        username: "alice",
      } as unknown as { email: string; password: string }),
    ).resolves.toBeUndefined();

    expect(JSON.parse(String(seen[0]?.init?.body))).toEqual({
      email: "alice@example.com",
      password: "password123",
    });
    expect(__getAuthStandIn()).toContain("flock_session=");
  });

  it("mock enforces extra=forbid with 422 when unknown keys reach the wire", async () => {
    const res = await fetch(`${BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        email: "alice@example.com",
        password: "password123",
        username: "alice",
      }),
    });

    expect(res.status).toBe(422);
    expect(await res.json()).toEqual({
      error: { code: "validation_error", fields: { username: "invalid" } },
    });
    expect(__getAuthStandIn()).toBeNull();
  });

  it("malformed email rejects with 422 email invalid without ending the session", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await expect(
      gateway.login({ email: "not-an-email", password: "password123" }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      fields: { email: "invalid" },
    });
    expect(onSessionEnd).not.toHaveBeenCalled();
    expect(__getAuthStandIn()).toBeNull();
  });

  it("origin denial passes 403 through without ending the session", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });
    __setLoginOriginAllowed(false);
    try {
      await expect(
        gateway.login({ email: "alice@example.com", password: "password123" }),
      ).rejects.toMatchObject({
        status: 403,
        code: "origin_not_allowed",
      });
    } finally {
      __setLoginOriginAllowed(true);
    }
    expect(onSessionEnd).not.toHaveBeenCalled();
    expect(__getAuthStandIn()).toBeNull();
  });

  it("logout ends the session via POST /auth/logout", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await gateway.login({
      email: "alice@example.com",
      password: "password123",
    });
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
