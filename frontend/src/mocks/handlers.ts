import { HttpResponse, http } from "msw";
import type { User } from "@/lib/api/port";

/**
 * PROVISIONAL cookie-session stand-in (mock-first, MSW only).
 * The real backend sets `Set-Cookie: session` (name PROVISIONAL) on
 * POST /auth/login; MSW emulates it with an in-memory stand-in plus a
 * `Set-Cookie` header on the mocked response. Swap stays mechanical:
 * point NEXT_PUBLIC_API_URL at the real backend and delete this file's
 * usages. There is intentionally NO `GET /auth/me` handler — a 401 on any
 * request IS the guard (session clears and the app routes to /login).
 */
const SESSION_COOKIE = "session";

interface Account extends User {
  password: string;
}

const accounts = new Map<string, Account>([
  [
    "alice",
    {
      id: "u-alice",
      username: "alice",
      bio: "Test user",
      avatarUrl: null,
      password: "password123",
    },
  ],
]);

let sessionStandIn: string | null = null;

/** Test-only accessor for the PROVISIONAL stand-in (never ship to prod code). */
export function __getAuthStandIn(): string | null {
  return sessionStandIn;
}

/** Test-only reset for the PROVISIONAL stand-in. */
export function __resetAuthStandIn(): void {
  sessionStandIn = null;
}

function publicUser(account: Account): User {
  return {
    id: account.id,
    username: account.username,
    bio: account.bio,
    avatarUrl: account.avatarUrl,
  };
}

/** S1 only: login/logout. S2/S3 append tweet/follow handlers here. */
export const handlers = [
  http.post("*/auth/login", async ({ request }) => {
    const body = (await request.json()) as {
      username?: string;
      password?: string;
    };
    const account = accounts.get((body.username ?? "").trim().toLowerCase());
    if (account === undefined || account.password !== body.password) {
      return HttpResponse.json(
        { detail: "Invalid credentials" },
        { status: 401 },
      );
    }
    sessionStandIn = `${SESSION_COOKIE}=${account.username}-session`;
    return HttpResponse.json(publicUser(account), {
      status: 200,
      headers: {
        "Set-Cookie": `${sessionStandIn}; Path=/; HttpOnly; SameSite=Lax`,
      },
    });
  }),

  http.post("*/auth/logout", () => {
    sessionStandIn = null;
    return HttpResponse.json(
      { ok: true },
      { headers: { "Set-Cookie": `${SESSION_COOKIE}=; Path=/; Max-Age=0` } },
    );
  }),

  // NOTE: no GET /auth/me handler by decision — 401-anywhere is the guard.
];
