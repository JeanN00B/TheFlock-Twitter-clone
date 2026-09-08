import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  __resetAuthStandIn,
  __resetTweets,
  __seedTweet,
} from "@/mocks/handlers";
import { createBackendGateway } from "./fetch-client";
import { ApiError } from "./port";

const BASE_URL = "http://localhost:8000";

beforeEach(() => {
  __resetAuthStandIn();
  __resetTweets();
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

describe("setLike contract", () => {
  it("likes and unlikes with the exact like-state envelope", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    const tweet = __seedTweet({ username: "bob", text: "like me" });

    const liked = await gateway.setLike({ tweetId: tweet.id, liked: true });
    expect(liked).toEqual({
      tweetId: tweet.id,
      likeCount: 1,
      likedByActor: true,
    });

    const page = await gateway.feed();
    expect(page.items[0]).toMatchObject({
      id: tweet.id,
      likeCount: 1,
      likedByActor: true,
    });

    const unliked = await gateway.setLike({ tweetId: tweet.id, liked: false });
    expect(unliked).toEqual({
      tweetId: tweet.id,
      likeCount: 0,
      likedByActor: false,
    });
  });

  it("rejects unknown and malformed tweet ids", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();

    await expect(
      gateway.setLike({
        tweetId: "12345678-1234-4234-8234-1234567890ab",
        liked: true,
      }),
    ).rejects.toMatchObject({ status: 404, code: "not_found" });

    await expect(
      gateway.setLike({ tweetId: "nope", liked: true }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      fields: { tweet_id: "invalid" },
    });
  });

  it("401 ends the session for logged-out likes", async () => {
    const onSessionEnd = vi.fn();
    const gateway = createBackendGateway(BASE_URL, { onSessionEnd });

    await expect(
      gateway.setLike({
        tweetId: "12345678-1234-4234-8234-1234567890ab",
        liked: true,
      }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
  });
});
