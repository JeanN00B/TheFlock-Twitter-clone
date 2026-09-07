/** S1 port: cookie-session auth boundary (S2/S3 extend this gateway). */

export interface User {
  id: string;
  username: string;
  bio: string | null;
  avatarUrl: string | null;
}

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

/** PROVISIONAL tweet shape (per design; mapping isolated in the adapter). */
export interface Tweet {
  id: string;
  authorUsername: string;
  text: string;
  createdAt: string;
}

export interface PostTweetInput {
  text: string;
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

/** Single gateway port. S1 owns login/logout; S2/S3 add tweet/follow methods. */
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
  /** POST /auth/logout — ends the cookie session. */
  logout(): Promise<void>;
  /**
   * POST /tweet — creates a tweet over the cookie session.
   * Rejects ApiError(401) when logged out, ApiError(422) when the
   * server refuses the text (over 280 chars, empty). The server is
   * the authority; the client-side 280 rule is UX only.
   */
  createTweet(input: PostTweetInput): Promise<Tweet>;
  /** GET /tweet — reads the timeline over the cookie session. */
  timeline(): Promise<Tweet[]>;
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
