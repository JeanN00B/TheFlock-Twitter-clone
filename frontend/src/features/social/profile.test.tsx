import {
  fireEvent,
  type RenderResult,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { act, Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProfilePage from "@/app/profile/[username]/page";
import { AppProviders } from "@/app/providers";
import { SESSION_STORAGE_KEY } from "@/features/auth/session-store";
import { createBackendGateway } from "@/lib/api/fetch-client";
import type { User } from "@/lib/api/port";
import {
  __resetAuthStandIn,
  __resetFollows,
  __resetTweets,
} from "@/mocks/handlers";

const BASE_URL = "http://localhost:8000";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const alice: User = {
  id: "u-alice",
  username: "alice",
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
    username: "alice",
    password: "password123",
  });
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
});
