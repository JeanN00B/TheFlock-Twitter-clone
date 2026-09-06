/** S1 port: cookie-session auth boundary (S2/S3 extend this gateway). */

export interface User {
  id: string;
  username: string;
  bio: string | null;
  avatarUrl: string | null;
}

export type SessionView = { user: User } | null;

export interface LoginInput {
  username: string;
  password: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: string;

  constructor(status: number, detail?: string) {
    super(detail ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Single gateway port. S1 owns login/logout; S2/S3 add tweet/follow methods. */
export interface BackendGateway {
  /** POST /auth/login — resolves with the user on success, rejects ApiError(401) otherwise. */
  login(input: LoginInput): Promise<User>;
  /** POST /auth/logout — ends the cookie session. */
  logout(): Promise<void>;
}
