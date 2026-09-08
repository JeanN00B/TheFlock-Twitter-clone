/** P2 port: cookie-session auth boundary plus the real /tweets seam. */

export interface User {
  id: string;
  username: string;
  /** Shown in the header as the display name; never render `email` (see below). */
  displayName: string;
  createdAt: string;
  updatedAt: string;
  bio: string | null;
  avatarUrl: string | null;
}

/**
 * Email decision (documented): GET /auth/me also returns `email`, but the
 * adapter drops it at the boundary and it never enters this port. The
 * header renders displayName/@username only, and keeping PII out of the
 * PUBLIC sessionStorage mirror minimizes exposure. Revisit only if a
 * rendered surface genuinely needs the address.
 */

export type SessionView = { user: User } | null;

export interface LoginInput {
  email: string;
  password: string;
}

export interface RegisterInput {
  email: string;
  username: string;
  displayName: string;
  password: string;
}

export interface RegistrationResult {
  id: string;
  username: string;
  displayName: string;
  email: string;
  createdAt: string;
  updatedAt: string;
}

/** P2 tweet shape: nested author identity (backend /tweets wire shape). */
export interface TweetAuthor {
  id: string;
  username: string;
  displayName: string;
}

export interface Tweet {
  id: string;
  text: string;
  createdAt: string;
  author: TweetAuthor;
}

export interface PostTweetInput {
  text: string;
}

/** P2 cursor page: items newest-first plus the opaque next cursor (null = caught up). */
export interface FeedPage {
  items: Tweet[];
  nextCursor: string | null;
}

export interface FeedInput {
  /** 1–50; omitted means the backend default (20). */
  pageSize?: number;
  /** Opaque cursor from the previous page; omitted for the first page. */
  cursor?: string;
}

/** S3 input: declaratively set follow state for a profile (not a blind toggle). */
export interface ToggleFollowInput {
  username: string;
  /** Desired state: true to follow, false to unfollow. */
  following: boolean;
}

/** S3 result of a follow-state change. */
export interface FollowState {
  username: string;
  following: boolean;
  followersCount: number;
}

/** S3 profile view over the cookie session. */
export interface ProfileView {
  user: User;
  /** Whether the session user follows this profile. */
  following: boolean;
  followersCount: number;
  followingCount: number;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: string;
  readonly code?: string;
  readonly fields?: Record<string, string>;

  constructor(
    status: number,
    detail?: string,
    options?: { code?: string; fields?: Record<string, string> },
  ) {
    super(detail ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = options?.code;
    this.fields = options?.fields;
  }
}

/** Single gateway port. S1 owns login/logout/me; P2 owns the /tweets seam. */
export interface BackendGateway {
  /** POST /auth/register — creates an account without establishing a session. */
  register(input: RegisterInput): Promise<RegistrationResult>;
  /**
   * POST /auth/login — resolves empty on 204 success (the session lives in
   * the httpOnly cookie; there is no user body). Rejects ApiError(401)
   * invalid_credentials, ApiError(422) validation_error with fields, or
   * ApiError(403) origin_not_allowed.
   */
  login(input: LoginInput): Promise<void>;
  /**
   * GET /auth/me — reads the session identity over the cookie session.
   * Maps the backend snake_case user (display_name, created_at,
   * updated_at) to camelCase; `email` is dropped at the adapter boundary
   * (see above). Rejects ApiError(401) unauthenticated when logged out —
   * central session-end still applies; callers decide the outcome
   * (login-form treats it as failure, the shell treats it as signed-out).
   */
  me(): Promise<User>;
  /** POST /auth/logout — ends the cookie session. */
  logout(): Promise<void>;
  /**
   * POST /tweets — creates a tweet over the cookie session.
   * Rejects ApiError(401) when logged out, ApiError(422) when the
   * server refuses the text (over 280 chars, empty). The server is
   * the authority; the client-side 280 rule is UX only.
   */
  createTweet(input: PostTweetInput): Promise<Tweet>;
  /**
   * GET /tweets — reads one newest-first cursor page over the cookie
   * session. Rejects ApiError(401) unauthenticated when logged out,
   * ApiError(422) validation_error with fields for a bad page_size or
   * cursor. `nextCursor: null` means the list is caught up.
   */
  feed(input?: FeedInput): Promise<FeedPage>;
  /**
   * DELETE /tweets/{id} — deletes an own tweet over the cookie session.
   * Resolves void on 204. Rejects ApiError(403) forbidden (not the
   * author), ApiError(404) not_found (already gone), ApiError(422)
   * validation_error with fields for a malformed id.
   */
  deleteTweet(id: string): Promise<void>;
  /**
   * GET /profile/:username — reads a profile over the cookie session.
   * Rejects ApiError(401) when logged out.
   */
  profile(username: string): Promise<ProfileView>;
  /**
   * POST /follow — sets follow state over the cookie session.
   * Rejects ApiError(401) when logged out, ApiError(422) when the
   * server refuses the change (unknown shape, self-follow).
   */
  setFollow(input: ToggleFollowInput): Promise<FollowState>;
}
