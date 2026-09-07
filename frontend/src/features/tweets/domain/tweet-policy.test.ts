import { describe, expect, it } from "vitest";
import {
  canPostTweet,
  TWEET_MAX_LENGTH,
  validateTweetText,
} from "./tweet-policy";

describe("tweet-policy seam (S2)", () => {
  it("accepts exactly 280 characters", () => {
    expect(TWEET_MAX_LENGTH).toBe(280);
    expect(validateTweetText("x".repeat(280))).toEqual({ ok: true });
    expect(canPostTweet("x".repeat(280))).toBe(true);
  });

  it("blocks 281 characters (server 422 stays the authority)", () => {
    const result = validateTweetText("x".repeat(281));
    expect(result).toEqual({ ok: false, reason: "too_long" });
    expect(canPostTweet("x".repeat(281))).toBe(false);
  });

  it("blocks empty and whitespace-only text", () => {
    expect(validateTweetText("")).toEqual({ ok: false, reason: "empty" });
    expect(validateTweetText("   \n\t  ")).toEqual({
      ok: false,
      reason: "empty",
    });
    expect(canPostTweet("")).toBe(false);
    expect(canPostTweet("   \n\t  ")).toBe(false);
  });

  it("accepts normal text", () => {
    expect(canPostTweet("Hello, flock!")).toBe(true);
  });
});
