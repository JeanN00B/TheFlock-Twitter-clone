import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { AppProviders } from "@/app/providers";
import { SESSION_STORAGE_KEY } from "@/features/auth/session-store";
import { ComposerProvider } from "@/features/tweets/composer-dialog";
import { createBackendGateway } from "@/lib/api/fetch-client";
import type { User } from "@/lib/api/port";
import {
  __resetAuthStandIn,
  __resetTweets,
  __seedTweet,
} from "@/mocks/handlers";
import ShellLayout from "./layout";
import Home from "./page";

const BASE_URL = "http://localhost:8000";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/",
}));

const alice: User = {
  id: "u-alice",
  username: "alice",
  displayName: "Alice",
  createdAt: "2024-01-01T00:00:00.000Z",
  updatedAt: "2024-01-01T00:00:00.000Z",
  bio: "Test user",
  avatarUrl: null,
};

function renderHome() {
  return render(
    <AppProviders>
      <ComposerProvider>
        <Home />
      </ComposerProvider>
    </AppProviders>,
  );
}

/**
 * Shell-owned identity stand-in: production Home always mounts inside
 * ShellLayout (me() restore), but these tests render Home directly, so
 * the PUBLIC mirror seeds the same identity here.
 */
function seedSessionMirror() {
  sessionStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({ user: alice }),
  );
}

async function loginAsAlice() {
  await createBackendGateway(BASE_URL).login({
    email: "alice@example.com",
    password: "password123",
  });
}

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  __resetAuthStandIn();
  __resetTweets();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("home feed (P2)", () => {
  it("authenticated home shows real posts newest-first over a cookie session", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    await gateway.createTweet({ text: "seeded older" });
    await gateway.createTweet({ text: "seeded newer" });
    seedSessionMirror();
    renderHome();

    expect(await screen.findByText("seeded newer")).toBeInTheDocument();
    expect(screen.getAllByText("@alice")).toHaveLength(2);
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("seeded newer");
    expect(items[1]).toHaveTextContent("seeded older");
  });

  it("keeps Home on the existing global feed URL", async () => {
    await loginAsAlice();
    __seedTweet({ username: "bob", text: "global home row" });
    seedSessionMirror();
    const urls: string[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        urls.push(String(input));
        return realFetch(input, init);
      },
    );

    renderHome();
    expect(await screen.findByText("global home row")).toBeInTheDocument();
    const feedUrl = new URL(urls.find((url) => url.includes("/tweets")) ?? "");
    expect(feedUrl.searchParams.has("feed")).toBe(false);
    expect(feedUrl.searchParams.has("username")).toBe(false);
  });

  it("server stays authority: 281 chars rejects with 422", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();

    await expect(
      gateway.createTweet({ text: "x".repeat(281) }),
    ).rejects.toMatchObject({ status: 422 });
    await expect(gateway.createTweet({ text: "   " })).rejects.toMatchObject({
      status: 422,
    });
  });

  it("delete-own commits on 204 and the row stays gone", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    await gateway.createTweet({ text: "doomed post" });
    seedSessionMirror();
    renderHome();

    expect(await screen.findByText("doomed post")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /delete post by @alice/i }),
    );

    await waitFor(() =>
      expect(screen.queryByText("doomed post")).not.toBeInTheDocument(),
    );
    const page = await gateway.feed();
    expect(page.items.map((tweet) => tweet.text)).not.toContain("doomed post");
  });

  it("load-more fallback pages to caught-up", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    for (let index = 0; index < 22; index += 1) {
      await gateway.createTweet({ text: `post ${index}` });
    }
    seedSessionMirror();
    renderHome();

    await waitFor(() =>
      expect(screen.getAllByRole("listitem")).toHaveLength(20),
    );
    fireEvent.click(screen.getByRole("button", { name: /load more/i }));

    await waitFor(() =>
      expect(screen.getAllByRole("listitem")).toHaveLength(22),
    );
    expect(screen.getByText(/you're caught up/i)).toBeInTheDocument();
  });

  it("logged-out home 401 clears the mirror and routes to /login", async () => {
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ user: alice }),
    );
    renderHome();

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it("StrictMode root double-mount still loads the feed and shows dialog posts", async () => {
    // Fix-1 regression: Next.js wraps the app in StrictMode at the ROOT
    // (outside providers), whose double-effect left the shared single-flight
    // ref raised and `loading` stuck true — FeedList then hid every row, so
    // a successful post never appeared. Dev source-of-truth is ruled out as
    // a cause: no browser MSW worker exists (msw/node is test-only), so dev
    // POST and GET share NEXT_PUBLIC_API_URL and the backend sorts
    // newest-first; the posted-token reload path already bypasses the
    // cursor. Home is Dialog-only now, so the post half goes through the
    // shell New-post trigger.
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    await gateway.createTweet({ text: "seeded visible" });
    seedSessionMirror();
    render(
      <StrictMode>
        <AppProviders>
          <ShellLayout>
            <Home />
          </ShellLayout>
        </AppProviders>
      </StrictMode>,
    );

    expect(await screen.findByText("seeded visible")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /new post/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/what's happening/i), {
      target: { value: "fresh strict post" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: /^post$/i }),
    );

    await waitFor(() =>
      expect(screen.getByText("fresh strict post")).toBeInTheDocument(),
    );
  });
});
