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
  // Strip-then-check mirrors the backend (normalize_tweet_text): surrounding
  // whitespace never counts toward the 280, and whitespace-only is empty.
  const stripped = text.trim();
  if (stripped.length === 0) return { ok: false, reason: "empty" };
  if (stripped.length > TWEET_MAX_LENGTH)
    return { ok: false, reason: "too_long" };
  return { ok: true };
}

export function canPostTweet(text: string): boolean {
  return validateTweetText(text).ok;
}
