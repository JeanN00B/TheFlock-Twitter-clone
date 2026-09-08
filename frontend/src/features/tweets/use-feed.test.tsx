import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppProviders } from "@/app/providers";
import { createBackendGateway } from "@/lib/api/fetch-client";
import {
  __resetAuthStandIn,
  __resetFollows,
  __resetTweets,
  __seedTweet,
} from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { useFeed } from "./use-feed";

const BASE_URL = "http://localhost:8000";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

/** Controllable IntersectionObserver stand-in for sentinel tests. */
let observerCallback: IntersectionObserverCallback | null = null;
const observed = new Set<Element>();

class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | null = null;
  readonly rootMargin = "";
  readonly thresholds: ReadonlyArray<number> = [];
  constructor(callback: IntersectionObserverCallback) {
    observerCallback = callback;
  }
  observe(target: Element): void {
    observed.add(target);
  }
  unobserve(target: Element): void {
    observed.delete(target);
  }
  disconnect(): void {
    observed.clear();
  }
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

function fireIntersecting(): void {
  act(() => {
    observerCallback?.(
      [{ isIntersecting: true } as IntersectionObserverEntry],
      IntentionallyUnusedObserver(),
    );
  });
}

function IntentionallyUnusedObserver(): IntersectionObserver {
  return new MockIntersectionObserver(() => {});
}

function wrapper({ children }: { children: ReactNode }) {
  return <AppProviders>{children}</AppProviders>;
}

async function loginAsAlice() {
  await createBackendGateway(BASE_URL).login({
    email: "alice@example.com",
    password: "password123",
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  observerCallback = null;
  observed.clear();
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
  __resetAuthStandIn();
  __resetTweets();
  __resetFollows();
});

describe("useFeed (P2)", () => {
  it("loads the first page newest-first", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    await gateway.createTweet({ text: "older" });
    await gateway.createTweet({ text: "newer" });

    const { result } = renderHook(() => useFeed({ pageSize: 10 }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
      "newer",
      "older",
    ]);
    expect(result.current.hasMore).toBe(false);
  });

  it("sentinel auto-pages until caught up", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    for (const text of ["one", "two", "three"]) {
      await gateway.createTweet({ text });
    }

    const { result } = renderHook(() => useFeed({ pageSize: 2 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
      "three",
      "two",
    ]);
    expect(result.current.hasMore).toBe(true);

    const sentinel = document.createElement("div");
    act(() => {
      result.current.sentinelRef(sentinel);
    });
    expect(observed.has(sentinel)).toBe(true);

    fireIntersecting();
    await waitFor(() =>
      expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
        "three",
        "two",
        "one",
      ]),
    );
    expect(result.current.hasMore).toBe(false);
  });

  it("sentinel pages a profile scope without dropping its username", async () => {
    await loginAsAlice();
    __seedTweet({ username: "bob", text: "old bob" });
    __seedTweet({ username: "bob", text: "middle bob" });
    __seedTweet({ username: "bob", text: "new bob" });
    const calls: string[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        calls.push(String(input));
        return realFetch(input, init);
      },
    );

    const { result } = renderHook(
      () =>
        useFeed({
          pageSize: 2,
          scope: { kind: "profile", username: "bob" },
        }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    const sentinel = document.createElement("div");
    act(() => result.current.sentinelRef(sentinel));
    fireIntersecting();
    await waitFor(() => expect(result.current.tweets).toHaveLength(3));

    const pageCalls = calls.filter((url) => url.includes("/tweets"));
    expect(pageCalls).toHaveLength(2);
    for (const value of pageCalls) {
      const url = new URL(value);
      expect(url.searchParams.get("feed")).toBe("profile");
      expect(url.searchParams.get("username")).toBe("bob");
    }
  });

  it("single-flights duplicate page requests", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    for (const text of ["a", "b", "c"]) {
      await gateway.createTweet({ text });
    }
    const seen: string[] = [];
    const realFetch = globalThis.fetch;
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(
        async (input: Parameters<typeof fetch>[0], init) => {
          seen.push(String(input));
          return realFetch(input, init);
        },
      );

    const { result } = renderHook(() => useFeed({ pageSize: 2 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    spy.mockClear();

    act(() => {
      result.current.loadMore();
      result.current.loadMore();
    });
    await waitFor(() =>
      expect(result.current.tweets).toHaveLength(3),
    );

    const cursorCalls = seen.filter((url) => url.includes("cursor="));
    expect(cursorCalls).toHaveLength(1);
  });

  it("retry preserves loaded items and refires the same cursor", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    for (const text of ["x", "y", "z"]) {
      await gateway.createTweet({ text });
    }
    let attempts = 0;
    server.use(
      http.get("*/tweets", async ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.has("cursor")) {
          attempts += 1;
          if (attempts === 1) {
            return HttpResponse.json(
              { error: { code: "boom" } },
              { status: 500 },
            );
          }
        }
        return undefined;
      }),
    );

    const { result } = renderHook(() => useFeed({ pageSize: 2 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.loadMore();
    });
    await waitFor(() =>
      expect(result.current.loadMoreError).not.toBeNull(),
    );
    // Loaded items survive the page error.
    expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
      "z",
      "y",
    ]);

    act(() => {
      result.current.loadMore();
    });
    await waitFor(() =>
      expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
        "z",
        "y",
        "x",
      ]),
    );
    expect(result.current.loadMoreError).toBeNull();
    expect(result.current.hasMore).toBe(false);
  });

  it("retains profile scope and cursor on paging failure and retry", async () => {
    await loginAsAlice();
    __seedTweet({ username: "bob", text: "old bob" });
    __seedTweet({ username: "bob", text: "middle bob" });
    __seedTweet({ username: "bob", text: "new bob" });
    let attempts = 0;
    server.use(
      http.get("*/tweets", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.has("cursor")) {
          attempts += 1;
          if (attempts === 1) {
            return HttpResponse.json(
              { error: { code: "boom" } },
              { status: 500 },
            );
          }
        }
        return undefined;
      }),
    );
    const calls: string[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        calls.push(String(input));
        return realFetch(input, init);
      },
    );

    const { result } = renderHook(
      () =>
        useFeed({
          pageSize: 2,
          scope: { kind: "profile", username: "bob" },
        }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
      "new bob",
      "middle bob",
    ]);
    expect(result.current.hasMore).toBe(true);

    act(() => {
      result.current.loadMore();
    });
    await waitFor(() => expect(result.current.loadMoreError).not.toBeNull());
    expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
      "new bob",
      "middle bob",
    ]);

    act(() => {
      result.current.loadMore();
    });
    await waitFor(() => expect(result.current.tweets).toHaveLength(3));
    const pageCalls = calls.filter((url) => url.includes("/tweets"));
    expect(pageCalls).toHaveLength(3);
    const first = new URL(pageCalls[0] ?? "");
    const failed = new URL(pageCalls[1] ?? "");
    const retried = new URL(pageCalls[2] ?? "");
    expect(first.searchParams.get("feed")).toBe("profile");
    expect(first.searchParams.get("username")).toBe("bob");
    expect(failed.search).toBe(retried.search);
    expect(retried.searchParams.get("feed")).toBe("profile");
    expect(retried.searchParams.get("username")).toBe("bob");
  });

  it("retains following scope across sentinel paging", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    __seedTweet({ username: "bob", text: "bob-1" });
    __seedTweet({ username: "bob", text: "bob-2" });
    __seedTweet({ username: "bob", text: "bob-3" });
    __seedTweet({ username: "carol", text: "carol noise" });
    await gateway.setFollow({ username: "bob", following: true });

    const calls: string[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        calls.push(String(input));
        return realFetch(input, init);
      },
    );

    const { result } = renderHook(
      () => useFeed({ pageSize: 2, scope: { kind: "following" } }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
      "bob-3",
      "bob-2",
    ]);
    expect(result.current.hasMore).toBe(true);

    const sentinel = document.createElement("div");
    act(() => {
      result.current.sentinelRef(sentinel);
    });
    fireIntersecting();
    await waitFor(() =>
      expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
        "bob-3",
        "bob-2",
        "bob-1",
      ]),
    );
    expect(result.current.hasMore).toBe(false);

    const pageCalls = calls.filter((url) => url.includes("/tweets"));
    expect(pageCalls.length).toBeGreaterThanOrEqual(2);
    for (const value of pageCalls) {
      const url = new URL(value);
      expect(url.searchParams.get("feed")).toBe("following");
      expect(url.searchParams.has("username")).toBe(false);
    }
  });

  it("resets scope state and discards a late response from the old profile", async () => {
    await loginAsAlice();
    __seedTweet({ username: "alice", text: "alice row" });
    let releaseBob!: () => void;
    const bobGate = new Promise<void>((resolve) => {
      releaseBob = resolve;
    });
    let bobStarted = false;
    server.use(
      http.get("*/tweets", async ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("username") !== "bob") return undefined;
        bobStarted = true;
        await bobGate;
        return HttpResponse.json({
          items: [
            {
              id: "00000000-0000-4000-8000-000000000099",
              text: "late bob",
              created_at: "2024-01-01T00:00:00.000Z",
              author: {
                id: "u-bob",
                username: "bob",
                display_name: "Bob",
              },
              like_count: 0,
              liked_by_actor: false,
            },
          ],
          next_cursor: null,
        });
      }),
    );

    const { result, rerender } = renderHook(
      ({ username }: { username: string }) =>
        useFeed({ scope: { kind: "profile", username } }),
      { wrapper, initialProps: { username: "bob" } },
    );
    await waitFor(() => expect(bobStarted).toBe(true));

    rerender({ username: "alice" });
    await waitFor(() =>
      expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
        "alice row",
      ]),
    );
    releaseBob();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
      "alice row",
    ]);
  });

  it("discards a late profile page when reload starts a new generation", async () => {
    await loginAsAlice();
    __seedTweet({ username: "bob", text: "oldest bob" });
    __seedTweet({ username: "bob", text: "middle bob" });
    __seedTweet({ username: "bob", text: "newest bob" });
    let releasePage!: () => void;
    const pageGate = new Promise<void>((resolve) => {
      releasePage = resolve;
    });
    let pageStarted = false;
    server.use(
      http.get("*/tweets", async ({ request }) => {
        const url = new URL(request.url);
        if (
          url.searchParams.get("username") !== "bob" ||
          !url.searchParams.has("cursor")
        ) {
          return undefined;
        }
        pageStarted = true;
        await pageGate;
        return HttpResponse.json({
          items: [
            {
              id: "00000000-0000-4000-8000-000000000098",
              text: "late page",
              created_at: "2024-01-01T00:00:00.000Z",
              author: {
                id: "u-bob",
                username: "bob",
                display_name: "Bob",
              },
              like_count: 0,
              liked_by_actor: false,
            },
          ],
          next_cursor: null,
        });
      }),
    );

    const { result } = renderHook(
      () =>
        useFeed({
          pageSize: 2,
          scope: { kind: "profile", username: "bob" },
        }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
      "newest bob",
      "middle bob",
    ]);

    act(() => {
      result.current.loadMore();
    });
    await waitFor(() => expect(pageStarted).toBe(true));

    act(() => {
      result.current.reload();
    });
    await waitFor(() =>
      expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
        "newest bob",
        "middle bob",
      ]),
    );
    releasePage();
    await waitFor(() => expect(result.current.loadingMore).toBe(false));
    expect(result.current.tweets.map((tweet) => tweet.text)).toEqual([
      "newest bob",
      "middle bob",
    ]);
  });

  it("delete removes optimistically and commits on 204", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    const created = await gateway.createTweet({ text: "doomed" });

    const { result } = renderHook(() => useFeed({ pageSize: 10 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tweets.map((tweet) => tweet.id)).toContain(
      created.id,
    );

    await act(async () => {
      await result.current.removeTweet(created.id);
    });

    expect(result.current.tweets.map((tweet) => tweet.id)).not.toContain(
      created.id,
    );
    expect(result.current.deleteError).toBeNull();
  });

  it("delete rolls back with forbidden copy on 403", async () => {
    await loginAsAlice();
    const foreign = __seedTweet({ username: "bob", text: "not yours" });

    const { result } = renderHook(() => useFeed({ pageSize: 10 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.removeTweet(foreign.id).catch(() => {});
    });

    expect(result.current.tweets.map((tweet) => tweet.id)).toContain(
      foreign.id,
    );
    expect(result.current.deleteError).toMatch(/your own/i);
  });

  it("delete rolls back with gone copy on 404", async () => {
    await loginAsAlice();

    const { result } = renderHook(() => useFeed({ pageSize: 10 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current
        .removeTweet("12345678-1234-4234-8234-1234567890ab")
        .catch(() => {});
    });

    expect(result.current.deleteError).toMatch(/already gone/i);
  });

  it("likes optimistically and commits the authoritative count", async () => {
    await loginAsAlice();
    const foreign = __seedTweet({ username: "bob", text: "likeable" });

    const { result } = renderHook(() => useFeed({ pageSize: 10 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tweets[0]?.likedByActor).toBe(false);

    await act(async () => {
      await result.current.setTweetLike(foreign.id, true);
    });

    expect(result.current.tweets[0]).toMatchObject({
      id: foreign.id,
      likedByActor: true,
      likeCount: 1,
    });
    expect(result.current.likeError).toBeNull();
  });
});
