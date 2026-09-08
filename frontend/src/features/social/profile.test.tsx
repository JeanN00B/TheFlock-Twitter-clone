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
  __seedTweet,
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
  it("authenticated profile read shows the exact public identity, counts, initials, and Follow button", async () => {
    await loginAsAlice();
    await renderProfile("bob");

    expect(await screen.findByText("Bob", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("@bob", { exact: true })).toBeInTheDocument();
    expect(screen.getByText(/0 followers/)).toBeInTheDocument();
    expect(screen.getByText(/0 following/)).toBeInTheDocument();
    expect(screen.getByText("B", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("Test user")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
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

  it("unknown profile shows a local not-found state and keeps the session", async () => {
    await loginAsAlice();
    await renderProfile("ghostnobody");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This user was not found.",
    );
    expect(push).not.toHaveBeenCalledWith("/login");
  });

  it("invalid profile shows a local validation error and keeps the session", async () => {
    await loginAsAlice();
    await renderProfile("ab");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't load this profile.",
    );
    expect(push).not.toHaveBeenCalledWith("/login");
  });

  it("renders only the resolved profile's scoped posts", async () => {
    await loginAsAlice();
    __seedTweet({ username: "alice", text: "alice global row" });
    __seedTweet({ username: "bob", text: "bob profile row" });

    await renderProfile("BoB");

    expect(await screen.findByText("bob profile row")).toBeInTheDocument();
    expect(screen.queryByText("alice global row")).toBeNull();
  });

  it("uses the canonical profile username after profile resolution", async () => {
    await loginAsAlice();
    __seedTweet({ username: "bob", text: "canonical bob row" });
    const calls = spyOnFetch();

    await renderProfile("BoB");
    await screen.findByText("canonical bob row");

    const profileIndex = calls.findIndex(
      (call) => new URL(call.url).pathname === "/users/BoB",
    );
    const feedIndex = calls.findIndex(
      (call) => new URL(call.url).pathname === "/tweets",
    );
    expect(profileIndex).toBeGreaterThanOrEqual(0);
    expect(feedIndex).toBeGreaterThan(profileIndex);
    const feedUrl = new URL(calls[feedIndex]?.url ?? "");
    expect(feedUrl.searchParams.get("feed")).toBe("profile");
    expect(feedUrl.searchParams.get("username")).toBe("bob");
  });

  it("shows the profile empty state without global substitution", async () => {
    await loginAsAlice();
    await renderProfile("bob");

    expect(
      await screen.findByText("No posts yet — be the first to share something."),
    ).toBeInTheDocument();
  });

  it("shows caught-up after a non-empty profile feed completes", async () => {
    await loginAsAlice();
    __seedTweet({ username: "bob", text: "caught up row" });

    await renderProfile("bob");

    expect(await screen.findByText("caught up row")).toBeInTheDocument();
    expect(await screen.findByText("You're caught up")).toBeInTheDocument();
  });

  it("keeps the resolved profile visible while its feed retries locally", async () => {
    await loginAsAlice();
    __seedTweet({ username: "bob", text: "retryable bob row" });
    let attempts = 0;
    server.use(
      http.get("*/tweets", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("feed") !== "profile") return undefined;
        attempts += 1;
        if (attempts === 1) {
          return HttpResponse.json(
            { error: { code: "internal" } },
            { status: 500 },
          );
        }
        return undefined;
      }),
    );

    await renderProfile("bob");
    expect(await screen.findByText("Bob", { exact: true })).toBeInTheDocument();
    expect(await screen.findByText("Couldn't load your feed.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("retryable bob row")).toBeInTheDocument();
  });

  it("keeps delete-own behavior for posts in a self profile scope", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    const created = await gateway.createTweet({ text: "self profile row" });
    seedSessionMirror();

    await renderProfile("ALICE");
    expect(await screen.findByText("self profile row")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /delete post by @alice/i }),
    );
    await waitFor(() =>
      expect(screen.queryByText("self profile row")).not.toBeInTheDocument(),
    );
    expect((await gateway.feed({ scope: { kind: "profile", username: "alice" } })).items).not.toContainEqual(
      expect.objectContaining({ id: created.id }),
    );
  });

  it("own profile shows no Follow button (others-only)", async () => {
    await loginAsAlice();
    seedSessionMirror();
    await renderProfile("alice");

    expect(await screen.findByText("Alice", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("@alice", { exact: true })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^follow$/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^following$/i })).toBeNull();
  });

  it("canonicalizes a mixed-case self URL before applying the self guard", async () => {
    await loginAsAlice();
    seedSessionMirror();
    await renderProfile("ALICE");

    expect(await screen.findByText("Alice", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("@alice", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("A", { exact: true })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^follow$/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^following$/i })).toBeNull();
  });
});
