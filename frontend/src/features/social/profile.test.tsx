import {
  fireEvent,
  type RenderResult,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { act, Suspense } from "react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProfilePage from "@/app/(shell)/profile/[username]/page";
import { AppProviders } from "@/app/providers";
import { SESSION_STORAGE_KEY } from "@/features/auth/session-store";
import { createBackendGateway } from "@/lib/api/fetch-client";
import type { User } from "@/lib/api/port";
import {
  __resetAuthStandIn,
  __resetFollows,
  __resetTweets,
} from "@/mocks/handlers";
import { server } from "@/mocks/server";

const BASE_URL = "http://localhost:8000";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const alice: User = {
  id: "u-alice",
  username: "alice",
  displayName: "Alice",
  createdAt: "2024-01-01T00:00:00.000Z",
  updatedAt: "2024-01-01T00:00:00.000Z",
  bio: "Test user",
  avatarUrl: null,
};

async function renderProfile(username: string): Promise<RenderResult> {
  // The page unwraps Next's async route params with `use()`, which
  // suspends on first render — await act so the suite observes the
  // resolved tree instead of the Suspense fallback.
  let tree!: RenderResult;
  await act(async () => {
    tree = render(
      <AppProviders>
        <Suspense fallback={<p>Loading profile…</p>}>
          <ProfilePage params={Promise.resolve({ username })} />
        </Suspense>
      </AppProviders>,
    );
  });
  return tree;
}

async function loginAsAlice() {
  await createBackendGateway(BASE_URL).login({
    email: "alice@example.com",
    password: "password123",
  });
}

function seedSessionMirror() {
  sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ user: alice }));
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

function realFollowPosts(
  calls: Array<{ url: string; init?: RequestInit }>,
  username: string,
) {
  return calls.filter(
    (call) =>
      new URL(call.url).pathname === `/users/${username}/follow` &&
      call.init?.method === "POST",
  );
}

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  __resetAuthStandIn();
  __resetTweets();
  __resetFollows();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("social seam (S3)", () => {
  it("authenticated profile read shows the user, follower count, and a Follow button", async () => {
    await loginAsAlice();
    await renderProfile("bob");

    expect(await screen.findByText("@bob")).toBeInTheDocument();
    expect(screen.getByText(/0 followers/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Follow" })).toBeInTheDocument();
  });

  it("Follow flips to Following and increments the count, never Authorization", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        calls.push({ url: String(input), init });
        return realFetch(input, init);
      },
    );
    await loginAsAlice();
    await renderProfile("bob");

    expect(await screen.findByText(/0 followers/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Follow" }));

    expect(
      await screen.findByRole("button", { name: "Following" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 follower/)).toBeInTheDocument();

    const toggles = calls.filter(
      (call) => call.url.includes("/follow") && call.init?.method === "POST",
    );
    expect(toggles).toHaveLength(1);
    expect(toggles[0]?.init?.credentials).toBe("include");
    expect(
      new Headers(toggles[0]?.init?.headers).get("authorization"),
    ).toBeNull();
  });

  it("Unfollow flips back to Follow and decrements the count", async () => {
    await loginAsAlice();
    await createBackendGateway(BASE_URL).setFollow({
      username: "bob",
      following: true,
    });
    await renderProfile("bob");

    expect(
      await screen.findByRole("button", { name: "Following" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 follower/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Following" }));

    expect(
      await screen.findByRole("button", { name: "Follow" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/0 followers/)).toBeInTheDocument();
  });

  it("logged-out profile 401 clears the mirror and routes to /login", async () => {
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ user: alice }),
    );
    await renderProfile("bob");

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it("follow lives on the profile only — no /search traffic or affordance", async () => {
    const urls: string[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        urls.push(String(input));
        return realFetch(input, init);
      },
    );
    await loginAsAlice();
    await renderProfile("bob");

    fireEvent.click(await screen.findByRole("button", { name: "Follow" }));
    await screen.findByRole("button", { name: "Following" });

    expect(urls.some((url) => url.includes("/search"))).toBe(false);
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.queryByRole("link", { name: /search/i })).toBeNull();
  });

  it("toggle is optimistic: Following + pending show before the response resolves", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post("*/users/bob/follow", async () => {
        await gate;
        return HttpResponse.json({ username: "bob", following: true });
      }),
    );
    await loginAsAlice();
    const calls = spyOnFetch();
    await renderProfile("bob");

    fireEvent.click(await screen.findByRole("button", { name: "Follow" }));

    // The real path is hit once, and the UI flips while gated.
    expect(realFollowPosts(calls, "bob")).toHaveLength(1);
    expect(
      await screen.findByRole("button", { name: /saving/i }),
    ).toBeDisabled();
    expect(screen.getByText(/1 follower/)).toBeInTheDocument();

    release();
    expect(
      await screen.findByRole("button", { name: "Following" }),
    ).toBeInTheDocument();
    // The real response carries no counts: the optimistic count stands.
    expect(screen.getByText(/1 follower/)).toBeInTheDocument();
  });

  it("failed toggle rolls back to Follow with a retry toast and no /login", async () => {
    server.use(
      http.post("*/users/bob/follow", () =>
        HttpResponse.json({ error: { code: "internal" } }, { status: 500 }),
      ),
    );
    await loginAsAlice();
    const calls = spyOnFetch();
    await renderProfile("bob");

    fireEvent.click(await screen.findByRole("button", { name: "Follow" }));

    expect(realFollowPosts(calls, "bob")).toHaveLength(1);
    expect(
      await screen.findByText("Couldn't update the follow. Please try again."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Follow" })).toBeInTheDocument();
    expect(screen.getByText(/0 followers/)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalledWith("/login");
  });

  it("follow on an unknown user rolls back with a not-found toast and keeps the session", async () => {
    await loginAsAlice();
    const calls = spyOnFetch();
    await renderProfile("ghost-nobody");

    // The frozen profile stand-in still renders; only the follow is real.
    expect(await screen.findByText("@ghost-nobody")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Follow" }));

    expect(realFollowPosts(calls, "ghost-nobody")).toHaveLength(1);
    expect(
      await screen.findByText("This user was not found."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Follow" })).toBeInTheDocument();
    // 404 is not 401: no central session end, no /login push.
    expect(push).not.toHaveBeenCalledWith("/login");
  });

  it("own profile shows no Follow button (others-only)", async () => {
    await loginAsAlice();
    seedSessionMirror();
    await renderProfile("alice");

    expect(await screen.findByText("@alice")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^follow$/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^following$/i })).toBeNull();
  });
});
