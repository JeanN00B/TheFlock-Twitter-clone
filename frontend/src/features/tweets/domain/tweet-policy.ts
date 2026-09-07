/**
 * S2 domain rule: client mirror of the 280-character tweet limit.
 * Pure (no framework, no I/O) so the composer can block over-limit posts
 * before any network call. The server stays the authority — over-limit
 * POSTs are rejected with 422 even if this client check is bypassed.
 */
export const TWEET_MAX_LENGTH = 280;

export type TweetValidation =
  | { ok: true }
  | { ok: false; reason: "empty" | "too_long" };

export function validateTweetText(text: string): TweetValidation {
  if (text.trim().length === 0) return { ok: false, reason: "empty" };
  if (text.length > TWEET_MAX_LENGTH) return { ok: false, reason: "too_long" };
  return { ok: true };
}

export function canPostTweet(text: string): boolean {
  return validateTweetText(text).ok;
}
