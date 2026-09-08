import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  __resetAuthStandIn,
  __resetFollows,
  __resetTweets,
  __seedTweet,
} from "@/mocks/handlers";
import { createBackendGateway } from "./fetch-client";
import { ApiError } from "./port";

const BASE_URL = "http://localhost:8000";

beforeEach(() => {
  __resetAuthStandIn();
  __resetTweets();
  __resetFollows();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function loginAsAlice() {
  await createBackendGateway(BASE_URL).login({
    email: "alice@example.com",
    password: "password123",
  });
}

describe("BackendGateway feed seam (P2)", () => {
  it("feed remaps nested-snake rows to domain camelCase", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    await gateway.createTweet({ text: "nested hello" });

    const page = await gateway.feed();

    expect(page.nextCursor).toBeNull();
    expect(page.items).toHaveLength(1);
    expect(page.items[0]).toEqual({
      id: expect.stringMatching(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      ),
      text: "nested hello",
      createdAt: expect.stringMatching(/Z$/),
      author: { id: "u-alice", username: "alice", displayName: "alice" },
    });
  });

  it("feed pages newest-first with cursor round-trip to caught-up", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    for (const text of ["one", "two", "three", "four", "five"]) {
      await gateway.createTweet({ text });
    }

    const first = await gateway.feed({ pageSize: 2 });
    expect(first.items.map((tweet) => tweet.text)).toEqual(["five", "four"]);
    expect(typeof first.nextCursor).toBe("string");

    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const second = await gateway.feed({ pageSize: 2, cursor: first.nextCursor! });
    expect(second.items.map((tweet) => tweet.text)).toEqual(["three", "two"]);
    expect(typeof second.nextCursor).toBe("string");

    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const third = await gateway.feed({ pageSize: 2, cursor: second.nextCursor! });
    expect(third.items.map((tweet) => tweet.text)).toEqual(["one"]);
    expect(third.nextCursor).toBeNull();
  });

  it("feed sends page_size and cursor as query params, never Authorization", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    for (const text of ["a", "b", "c", "d", "e", "f", "g", "h"]) {
      await gateway.createTweet({ text });
    }
    const first = await gateway.feed({ pageSize: 7 });
    expect(typeof first.nextCursor).toBe("string");

    const seen: Array<{ url: string; init?: RequestInit }> = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        seen.push({ url: String(input), init });
        return realFetch(input, init);
      },
    );

    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    await gateway.feed({ pageSize: 7, cursor: first.nextCursor! });

    const calls = seen.filter((call) => call.url.includes("/tweets?"));
    expect(calls).toHaveLength(1);
    const url = new URL(calls[0]?.url ?? "");
    expect(url.searchParams.get("page_size")).toBe("7");
    expect(url.searchParams.get("cursor")).toBe(first.nextCursor);
    expect(calls[0]?.init?.credentials).toBe("include");
    expect(
      new Headers(calls[0]?.init?.headers).get("authorization"),
    ).toBeNull();
  });

  it("feed omits cursor on the first page", async () => {
    const seen: string[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        seen.push(String(input));
        return realFetch(input, init);
      },
    );
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();

    await gateway.feed();

    const urls = seen.filter((url) => url.includes("/tweets"));
    expect(urls).toHaveLength(1);
    expect(new URL(urls[0] ?? "").searchParams.has("cursor")).toBe(false);
  });

  it("serializes the canonical profile scope on the first and cursor pages", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    __seedTweet({ username: "bob", text: "older bob" });
    __seedTweet({ username: "bob", text: "newer bob" });

    const seen: string[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        seen.push(String(input));
        return realFetch(input, init);
      },
    );

    const first = await gateway.feed({
      scope: { kind: "profile", username: "bob" },
      pageSize: 1,
    });
    expect(first.items.map((tweet) => tweet.author.username)).toEqual(["bob"]);
    expect(first.nextCursor).toEqual(expect.any(String));

    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    await gateway.feed({
      scope: { kind: "profile", username: "bob" },
      pageSize: 1,
      cursor: first.nextCursor!,
    });

    const tweetUrls = seen.filter((url) => url.includes("/tweets?"));
    expect(tweetUrls).toHaveLength(2);
    for (const [index, value] of tweetUrls.entries()) {
      const url = new URL(value);
      expect(url.searchParams.get("feed")).toBe("profile");
      expect(url.searchParams.get("username")).toBe("bob");
      expect(url.searchParams.get("page_size")).toBe("1");
      if (index === 0) expect(url.searchParams.has("cursor")).toBe(false);
      else expect(url.searchParams.has("cursor")).toBe(true);
    }
  });

  it("keeps an explicit all scope on the existing unscoped URL", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    __seedTweet({ username: "bob", text: "global row" });

    const seen: string[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        seen.push(String(input));
        return realFetch(input, init);
      },
    );

    await gateway.feed({ scope: { kind: "all" } });

    const url = new URL(seen.find((value) => value.includes("/tweets")) ?? "");
    expect(url.searchParams.has("feed")).toBe(false);
    expect(url.searchParams.has("username")).toBe(false);
  });

  it("serializes following scope and returns only followed authors", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    await gateway.createTweet({ text: "alice own" });
    __seedTweet({ username: "bob", text: "bob older" });
    __seedTweet({ username: "bob", text: "bob newer" });
    __seedTweet({ username: "carol", text: "carol row" });
    await gateway.setFollow({ username: "bob", following: true });

    const seen: string[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        seen.push(String(input));
        return realFetch(input, init);
      },
    );

    const first = await gateway.feed({
      scope: { kind: "following" },
      pageSize: 1,
    });
    expect(first.items.map((tweet) => tweet.text)).toEqual(["bob newer"]);
    expect(first.nextCursor).toEqual(expect.any(String));

    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const second = await gateway.feed({
      scope: { kind: "following" },
      pageSize: 1,
      cursor: first.nextCursor!,
    });
    expect(second.items.map((tweet) => tweet.text)).toEqual(["bob older"]);
    expect(second.nextCursor).toBeNull();

    const tweetUrls = seen.filter((url) => url.includes("/tweets?"));
    expect(tweetUrls).toHaveLength(2);
    for (const [index, value] of tweetUrls.entries()) {
      const url = new URL(value);
      expect(url.searchParams.get("feed")).toBe("following");
      expect(url.searchParams.has("username")).toBe(false);
      expect(url.searchParams.get("page_size")).toBe("1");
      if (index === 0) expect(url.searchParams.has("cursor")).toBe(false);
      else expect(url.searchParams.has("cursor")).toBe(true);
    }
  });

  it("rejects a cursor from another feed scope", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    __seedTweet({ username: "alice", text: "alice row" });
    __seedTweet({ username: "bob", text: "older bob" });
    __seedTweet({ username: "bob", text: "newer bob" });

    const global = await gateway.feed({ pageSize: 1 });
    await expect(
      gateway.feed({
        scope: { kind: "profile", username: "bob" },
        pageSize: 1,
        cursor: global.nextCursor ?? "",
      }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      fields: { cursor: "invalid" },
    });

    const bob = await gateway.feed({
      scope: { kind: "profile", username: "bob" },
      pageSize: 1,
    });
    await expect(
      gateway.feed({
        scope: { kind: "profile", username: "alice" },
        pageSize: 1,
        cursor: bob.nextCursor ?? "",
      }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      fields: { cursor: "invalid" },
    });

    await gateway.setFollow({ username: "bob", following: true });
    const following = await gateway.feed({
      scope: { kind: "following" },
      pageSize: 1,
    });
    await expect(
      gateway.feed({
        scope: { kind: "all" },
        pageSize: 1,
        cursor: following.nextCursor ?? "",
      }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      fields: { cursor: "invalid" },
    });
  });

  it("rejects missing or duplicate scope query parameters", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();

    const cases = [
      ["/tweets?feed=profile", { username: "invalid" }],
      ["/tweets?username=bob", { username: "invalid" }],
      ["/tweets?feed=profile&username=bob&username=bob", { username: "invalid" }],
      ["/tweets?feed=profile&feed=profile&username=bob", { feed: "invalid" }],
      ["/tweets?feed=profile&username=ab", { username: "invalid" }],
      ["/tweets?feed=following&username=bob", { username: "invalid" }],
    ] as const;

    for (const [path, fields] of cases) {
      const response = await fetch(`${BASE_URL}${path}`, {
        credentials: "include",
      });
      expect(response.status, path).toBe(422);
      await expect(response.json(), path).resolves.toEqual({
        error: { code: "validation_error", fields },
      });
    }
  });

  it("feed rejects a malformed cursor with 422 validation_error fields", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();

    await expect(
      gateway.feed({ cursor: "not-a-cursor!!" }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      fields: { cursor: "invalid" },
    });
  });

  it("feed rejects logged-out reads with 401 unauthenticated and ends the session", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await expect(gateway.feed()).rejects.toMatchObject({
      status: 401,
      code: "unauthenticated",
    });
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
  });

  it("createTweet posts to /tweets and maps the nested 201 row", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();

    const created = await gateway.createTweet({ text: "real post" });

    expect(created.author.username).toBe("alice");
    expect(created.text).toBe("real post");
  });

  it("deleteTweet resolves void on 204 and the row is gone", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    const created = await gateway.createTweet({ text: "doomed" });

    await expect(gateway.deleteTweet(created.id)).resolves.toBeUndefined();

    const page = await gateway.feed();
    expect(page.items.map((tweet) => tweet.id)).not.toContain(created.id);
  });

  it("deleteTweet rejects forbidden with 403 and keeps the row", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });
    await loginAsAlice();
    const foreign = __seedTweet({ username: "bob", text: "not yours" });

    await expect(gateway.deleteTweet(foreign.id)).rejects.toMatchObject({
      status: 403,
      code: "forbidden",
    });
    // 403 is an origin/ownership denial, never a session end.
    expect(onSessionEnd).not.toHaveBeenCalled();

    const page = await gateway.feed();
    expect(page.items.map((tweet) => tweet.id)).toContain(foreign.id);
  });

  it("deleteTweet rejects missing rows with 404 not_found", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();

    await expect(
      gateway.deleteTweet("12345678-1234-4234-8234-1234567890ab"),
    ).rejects.toMatchObject({ status: 404, code: "not_found" });
  });

  it("deleteTweet rejects malformed ids with 422 validation_error fields", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();

    await expect(gateway.deleteTweet("nope")).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      fields: { tweet_id: "invalid" },
    });
  });

  it("adapter rejects shape drift with 500 instead of leaking it", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({
          items: [{ id: "x", text: "drift", created_at: "now" }],
          next_cursor: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });

    await expect(gateway.feed()).rejects.toBeInstanceOf(ApiError);
    await expect(gateway.feed()).rejects.toMatchObject({ status: 500 });

    vi.mocked(globalThis.fetch).mockRestore();
    void realFetch;
  });
});
