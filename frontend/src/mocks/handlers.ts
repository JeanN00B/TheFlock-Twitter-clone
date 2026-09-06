import { HttpResponse, http } from "msw";
import type { Tweet, User } from "@/lib/api/port";

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

/** S1: login/logout. S2: tweet timeline/create. S3 appends follow handlers. */
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
