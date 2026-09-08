import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppProviders } from "@/app/providers";
import { createBackendGateway } from "@/lib/api/fetch-client";
import {
  __resetAuthStandIn,
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

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  observerCallback = null;
  observed.clear();
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
  __resetAuthStandIn();
  __resetTweets();
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
});
