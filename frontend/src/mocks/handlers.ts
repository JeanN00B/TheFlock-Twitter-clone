import { HttpResponse, http } from "msw";
import type { Tweet, User } from "@/lib/api/port";

/**
 * PROVISIONAL cookie-session stand-in (mock-first, MSW only).
 * The real backend answers POST /auth/login with 204 empty and sets
 * `Set-Cookie: flock_session` (host-only, HttpOnly, SameSite=Lax);
 * MSW emulates the cookie with an in-memory stand-in plus a `Set-Cookie`
 * header on the mocked response. Swap stays mechanical: point
 * NEXT_PUBLIC_API_URL at the real backend and delete this file's usages.
 * GET /auth/me mirrors the backend identity read over the cookie
 * stand-in below (logged out → 401 {error:{code:unauthenticated}}).
 */
const SESSION_COOKIE = "flock_session";

interface Account extends User {
  email: string;
  password: string;
}

const IDENTITY_CREATED_AT = "2024-01-01T00:00:00.000Z";

const accounts = new Map<string, Account>([
  [
    "alice",
    {
      id: "u-alice",
      username: "alice",
      displayName: "Alice",
      createdAt: IDENTITY_CREATED_AT,
      updatedAt: IDENTITY_CREATED_AT,
      email: "alice@example.com",
      bio: "Test user",
      avatarUrl: null,
      password: "password123",
    },
  ],
]);

interface RegistrationAccount {
  id: string;
  username: string;
  displayName: string;
  email: string;
  password: string;
  createdAt: string;
  updatedAt: string;
}

const initialRegistrationAccounts: RegistrationAccount[] = [
  {
    id: "00000000-0000-4000-8000-000000000001",
    username: "alice",
    displayName: "Alice",
    email: "alice@example.com",
    password: "password123",
    createdAt: "2024-01-01T00:00:00.000Z",
    updatedAt: "2024-01-01T00:00:00.000Z",
  },
];

const registrationAccounts = new Map<string, RegistrationAccount>(
  initialRegistrationAccounts.map((account): [string, RegistrationAccount] => [
    account.username,
    account,
  ]),
);

const REGISTRATION_EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const REGISTRATION_USERNAME_PATTERN = /^[a-z0-9_]{3,15}$/;

function registrationStringLength(value: string): number {
  return [...value].length;
}

function isValidRegistrationEmail(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const canonical = value.trim().toLowerCase();
  return (
    registrationStringLength(canonical) > 0 &&
    registrationStringLength(canonical) <= 254 &&
    REGISTRATION_EMAIL_PATTERN.test(canonical)
  );
}

function isValidRegistrationUsername(value: unknown): value is string {
  if (typeof value !== "string" || !/^[\x00-\x7f]*$/.test(value)) return false;
  return REGISTRATION_USERNAME_PATTERN.test(value.trim().toLowerCase());
}

function isValidRegistrationDisplayName(value: unknown): value is string {
  return (
    typeof value === "string" &&
    registrationStringLength(value.trim()) >= 1 &&
    registrationStringLength(value.trim()) <= 50
  );
}

function isValidRegistrationPassword(value: unknown): value is string {
  return (
    typeof value === "string" &&
    registrationStringLength(value) >= 8 &&
    registrationStringLength(value) <= 128
  );
}

function isValidRegistrationField(key: string, value: unknown): boolean {
  switch (key) {
    case "email":
      return isValidRegistrationEmail(value);
    case "username":
      return isValidRegistrationUsername(value);
    case "display_name":
      return isValidRegistrationDisplayName(value);
    case "password":
      return isValidRegistrationPassword(value);
    default:
      return false;
  }
}

let sessionStandIn: string | null = null;

/**
 * Test-only origin gate for POST /auth/login. The real backend denies
 * disallowed origins with 403 {error:{code:origin_not_allowed}} before
 * reading the body and without CORS headers; flipping this closed emulates
 * that denial. Defaults open; reset with the auth stand-in below.
 */
let loginOriginAllowed = true;

/** Test-only toggle for the login origin gate (never ship to prod code). */
export function __setLoginOriginAllowed(allowed: boolean): void {
  loginOriginAllowed = allowed;
}

/** Test-only accessor for the PROVISIONAL stand-in (never ship to prod code). */
export function __getAuthStandIn(): string | null {
  return sessionStandIn;
}

/** Test-only reset for the PROVISIONAL stand-in (also reopens the origin gate). */
export function __resetAuthStandIn(): void {
  sessionStandIn = null;
  loginOriginAllowed = true;
}

/** Test-only reset for stateful registration records. */
export function __resetRegistration(): void {
  registrationAccounts.clear();
  for (const account of initialRegistrationAccounts) {
    registrationAccounts.set(account.username, account);
  }
}

function publicUser(account: Account): User {
  return {
    id: account.id,
    username: account.username,
    displayName: account.displayName,
    createdAt: account.createdAt,
    updatedAt: account.updatedAt,
    bio: account.bio,
    avatarUrl: account.avatarUrl,
  };
}

/** S2: in-memory tweets. Reset per test; login stand-in above untouched. */
const TWEET_MAX_LENGTH = 280;
const tweets: Tweet[] = [];
let tweetSeq = 0;

/** Test-only reset for the S2 tweet store. */
export function __resetTweets(): void {
  tweets.length = 0;
  tweetSeq = 0;
}

/** S3: in-memory follows (follower -> followees). Reset per test; login stand-in and tweets above untouched. */
const follows = new Map<string, Set<string>>();

/** Test-only reset for the S3 follow store. */
export function __resetFollows(): void {
  follows.clear();
}

/** Number of session users currently following `username`. */
function followersOf(username: string): number {
  let count = 0;
  for (const followees of follows.values()) {
    if (followees.has(username)) count += 1;
  }
  return count;
}

/** Public user for a profile: known account, else a synthetic stand-in. */
function profileUser(username: string): User {
  const account = accounts.get(username.toLowerCase());
  if (account !== undefined) return publicUser(account);
  return {
    id: `u-${username.toLowerCase()}`,
    username,
    displayName: username,
    createdAt: IDENTITY_CREATED_AT,
    updatedAt: IDENTITY_CREATED_AT,
    bio: null,
    avatarUrl: null,
  };
}

/** Username behind the PROVISIONAL session stand-in, or null when logged out. */
function currentSessionUsername(): string | null {
  if (sessionStandIn === null) return null;
  const value = sessionStandIn.split("=").slice(1).join("=");
  if (!value.endsWith("-session")) return null;
  const username = value.slice(0, "-session".length * -1);
  return username === "" ? null : username;
}

function requireSession() {
  const username = currentSessionUsername();
  if (username === null) {
    return {
      username: null as string | null,
      response: HttpResponse.json(
        { detail: "Unauthenticated" },
        { status: 401 },
      ),
    };
  }
  return { username, response: null };
}

/** S1: login/logout. Registration remains explicitly signed out. */
export const handlers = [
  http.post("*/auth/register", async ({ request }) => {
    const body: unknown = await request.json();
    const expectedKeys = ["email", "username", "display_name", "password"];
    const fields: Record<string, string> = {};

    if (body === null || typeof body !== "object") {
      for (const key of expectedKeys) fields[key] = "invalid";
    } else {
      const record = body as Record<string, unknown>;
      for (const key of expectedKeys) {
        if (!isValidRegistrationField(key, record[key])) {
          fields[key] = "invalid";
        }
      }
      for (const key of Object.keys(record)) {
        if (!expectedKeys.includes(key)) fields[key] = "invalid";
      }
    }

    const record = body as Record<string, unknown>;
    if (Object.keys(fields).length > 0) {
      return HttpResponse.json(
        { error: { code: "validation_error", fields } },
        { status: 422 },
      );
    }

    const email = (record.email as string).trim().toLowerCase();
    const username = (record.username as string).trim().toLowerCase();
    const conflicts: Record<string, string> = {};
    for (const account of registrationAccounts.values()) {
      if (account.email === email) conflicts.email = "already_exists";
      if (account.username === username) conflicts.username = "already_exists";
    }
    if (Object.keys(conflicts).length > 0) {
      return HttpResponse.json(
        { error: { code: "conflict", fields: conflicts } },
        { status: 409 },
      );
    }

    const now = new Date().toISOString();
    const account: RegistrationAccount = {
      id: crypto.randomUUID(),
      username,
      displayName: (record.display_name as string).trim(),
      email,
      password: record.password as string,
      createdAt: now,
      updatedAt: now,
    };
    registrationAccounts.set(account.username, account);
    return HttpResponse.json(
      {
        id: account.id,
        username: account.username,
        display_name: account.displayName,
        email: account.email,
        created_at: account.createdAt,
        updated_at: account.updatedAt,
      },
      { status: 201 },
    );
  }),

  http.post("*/auth/login", async ({ request }) => {
    // Origin gate runs before the body is read, exactly like the backend
    // middleware: denial carries no CORS headers.
    if (!loginOriginAllowed) {
      return HttpResponse.json(
        { error: { code: "origin_not_allowed" } },
        { status: 403 },
      );
    }
    const body: unknown = await request.json();
    // Backend schema is exactly {email,password} (strict strings,
    // extra=forbid): anything else is 422 with per-field markers.
    const fields: Record<string, string> = {};
    if (body === null || typeof body !== "object") {
      fields.email = "invalid";
      fields.password = "invalid";
    } else {
      const record = body as Record<string, unknown>;
      for (const key of ["email", "password"]) {
        if (typeof record[key] !== "string") fields[key] = "invalid";
      }
      for (const key of Object.keys(record)) {
        if (key !== "email" && key !== "password") fields[key] = "invalid";
      }
    }
    if (Object.keys(fields).length > 0) {
      return HttpResponse.json(
        { error: { code: "validation_error", fields } },
        { status: 422 },
      );
    }
    // Backend use case canonicalizes the email (trim, lowercase, syntax):
    // a malformed address is 422, never 401.
    const record = body as Record<string, unknown>;
    const canonicalEmail = (record.email as string).trim().toLowerCase();
    if (
      canonicalEmail.length === 0 ||
      canonicalEmail.length > 254 ||
      !REGISTRATION_EMAIL_PATTERN.test(canonicalEmail)
    ) {
      return HttpResponse.json(
        { error: { code: "validation_error", fields: { email: "invalid" } } },
        { status: 422 },
      );
    }
    const account = [...accounts.values()].find(
      (candidate) => candidate.email === canonicalEmail,
    );
    if (account === undefined || account.password !== record.password) {
      return HttpResponse.json(
        { error: { code: "invalid_credentials" } },
        { status: 401 },
      );
    }
    sessionStandIn = `${SESSION_COOKIE}=${account.username}-session`;
    return new HttpResponse(null, {
      status: 204,
      headers: {
        "Set-Cookie": `${sessionStandIn}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800`,
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

  // GET /auth/me mirrors the backend identity read: the snake_case user
  // over the cookie stand-in, or 401 {error:{code:unauthenticated}} logged out.
  http.get("*/auth/me", () => {
    const username = currentSessionUsername();
    const account =
      username === null ? undefined : accounts.get(username.toLowerCase());
    if (username === null || account === undefined) {
      return HttpResponse.json(
        { error: { code: "unauthenticated" } },
        { status: 401 },
      );
    }
    return HttpResponse.json({
      id: account.id,
      username: account.username,
      display_name: account.displayName,
      email: account.email,
      created_at: account.createdAt,
      updated_at: account.updatedAt,
    });
  }),

  http.get("*/tweet", () => {
    const { username, response } = requireSession();
    if (response !== null) return response;
    if (username === null) throw new Error("unreachable");
    return HttpResponse.json(tweets);
  }),

  http.post("*/tweet", async ({ request }) => {
    const { username, response } = requireSession();
    if (response !== null) return response;
    if (username === null) throw new Error("unreachable");
    const body = (await request.json()) as { text?: unknown };
    // Server is the authority on the 280 rule: the client blocks first,
    // but a bypassed client still gets 422 here.
    if (
      typeof body.text !== "string" ||
      body.text.trim().length === 0 ||
      body.text.length > TWEET_MAX_LENGTH
    ) {
      return HttpResponse.json(
        { detail: "Tweet must be 1-280 characters" },
        { status: 422 },
      );
    }
    tweetSeq += 1;
    const tweet: Tweet = {
      id: `t-${tweetSeq}`,
      authorUsername: username,
      text: body.text,
      createdAt: new Date().toISOString(),
    };
    tweets.unshift(tweet);
    return HttpResponse.json(tweet, { status: 201 });
  }),

  http.get("*/profile/:username", ({ params }) => {
    const { username: sessionUser, response } = requireSession();
    if (response !== null) return response;
    if (sessionUser === null) throw new Error("unreachable");
    const username = String(params.username ?? "");
    if (username.trim() === "") {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }
    const followees = follows.get(sessionUser) ?? new Set<string>();
    return HttpResponse.json({
      user: profileUser(username),
      following: followees.has(username),
      followersCount: followersOf(username),
      followingCount: (follows.get(username) ?? new Set<string>()).size,
    });
  }),

  http.post("*/follow", async ({ request }) => {
    const { username: sessionUser, response } = requireSession();
    if (response !== null) return response;
    if (sessionUser === null) throw new Error("unreachable");
    const body = (await request.json()) as {
      username?: unknown;
      following?: unknown;
    };
    if (
      typeof body.username !== "string" ||
      body.username.trim() === "" ||
      typeof body.following !== "boolean"
    ) {
      return HttpResponse.json(
        { detail: "username and following are required" },
        { status: 422 },
      );
    }
    const target = body.username;
    if (target.toLowerCase() === sessionUser.toLowerCase()) {
      return HttpResponse.json(
        { detail: "Cannot follow yourself" },
        { status: 422 },
      );
    }
    let followees = follows.get(sessionUser);
    if (followees === undefined) {
      followees = new Set<string>();
      follows.set(sessionUser, followees);
    }
    if (body.following) followees.add(target);
    else followees.delete(target);
    return HttpResponse.json({
      username: target,
      following: followees.has(target),
      followersCount: followersOf(target),
    });
  }),
];
