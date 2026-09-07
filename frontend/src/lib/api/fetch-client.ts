import {
  ApiError,
  type BackendGateway,
  type FollowState,
  type LoginInput,
  type PostTweetInput,
  type ProfileView,
  type RegisterInput,
  type RegistrationResult,
  type ToggleFollowInput,
  type Tweet,
  type User,
} from "./port";

export interface GatewayHooks {
  /**
   * Called when the session ends: any 401 response, or a successful logout.
   * The composition root wires this to session clear + navigation to /login.
   */
  onSessionEnd?: () => void;
}

interface ParsedError {
  detail?: string;
  code?: string;
  fields?: Record<string, string>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

function stringFields(value: unknown): Record<string, string> | undefined {
  if (!isRecord(value)) return undefined;
  const fields: Record<string, string> = {};
  for (const [key, field] of Object.entries(value)) {
    if (typeof field === "string") fields[key] = field;
  }
  return Object.keys(fields).length > 0 ? fields : undefined;
}

async function parseError(res: Response): Promise<ParsedError> {
  try {
    const body: unknown = await res.json();
    if (!isRecord(body)) return {};

    const nested = isRecord(body.error) ? body.error : undefined;
    return {
      detail: typeof body.detail === "string" ? body.detail : undefined,
      code: nested && typeof nested.code === "string" ? nested.code : undefined,
      fields: nested ? stringFields(nested.fields) : undefined,
    };
  } catch {
    // Non-JSON error body — fall back to status text below.
    return {};
  }
}

/**
 * Backend-to-port mapping for registration, isolated here so backend
 * snake_case never leaks through the frontend port.
 */
function mapRegistration(raw: unknown): RegistrationResult {
  if (
    isRecord(raw) &&
    typeof raw.id === "string" &&
    typeof raw.username === "string" &&
    typeof raw.display_name === "string" &&
    typeof raw.email === "string" &&
    typeof raw.created_at === "string" &&
    typeof raw.updated_at === "string"
  ) {
    return {
      id: raw.id,
      username: raw.username,
      displayName: raw.display_name,
      email: raw.email,
      createdAt: raw.created_at,
      updatedAt: raw.updated_at,
    };
  }
  throw new ApiError(500, "Unexpected registration shape");
}

/**
 * Backend-to-port mapping, isolated here so a future shape change is a
 * mechanical swap. Rejects anything that is not a well-formed Tweet.
 */
function mapTweet(raw: unknown): Tweet {
  if (
    raw !== null &&
    typeof raw === "object" &&
    typeof (raw as { id?: unknown }).id === "string" &&
    typeof (raw as { authorUsername?: unknown }).authorUsername === "string" &&
    typeof (raw as { text?: unknown }).text === "string" &&
    typeof (raw as { createdAt?: unknown }).createdAt === "string"
  ) {
    return raw as Tweet;
  }
  throw new ApiError(500, "Unexpected tweet shape");
}

/**
 * Backend-to-port mapping for users, isolated here like mapTweet so a
 * future shape change is a mechanical swap. Accepts the backend snake_case
 * identity shape (GET /auth/me: display_name, created_at, updated_at) as
 * well as the camelCase profile shape. `email` is intentionally dropped
 * here and never enters the port (PII minimization — see port.ts).
 */
function mapUser(raw: unknown): User {
  if (!isRecord(raw)) throw new ApiError(500, "Unexpected user shape");
  const displayName = raw.displayName ?? raw.display_name;
  const createdAt = raw.createdAt ?? raw.created_at;
  const updatedAt = raw.updatedAt ?? raw.updated_at;
  const avatarUrl = raw.avatarUrl ?? raw.avatar_url;
  if (
    typeof raw.id === "string" &&
    typeof raw.username === "string" &&
    typeof displayName === "string" &&
    typeof createdAt === "string" &&
    typeof updatedAt === "string" &&
    (raw.bio === undefined || raw.bio === null || typeof raw.bio === "string") &&
    (avatarUrl === undefined || avatarUrl === null || typeof avatarUrl === "string")
  ) {
    return {
      id: raw.id,
      username: raw.username,
      displayName,
      createdAt,
      updatedAt,
      bio: typeof raw.bio === "string" ? raw.bio : null,
      avatarUrl: typeof avatarUrl === "string" ? avatarUrl : null,
    };
  }
  throw new ApiError(500, "Unexpected user shape");
}

/**
 * Backend-to-port mapping for follow-state changes, isolated here.
 * Rejects anything that is not a well-formed FollowState.
 */
function mapFollowState(raw: unknown): FollowState {
  if (
    raw !== null &&
    typeof raw === "object" &&
    typeof (raw as { username?: unknown }).username === "string" &&
    typeof (raw as { following?: unknown }).following === "boolean" &&
    typeof (raw as { followersCount?: unknown }).followersCount === "number"
  ) {
    return raw as FollowState;
  }
  throw new ApiError(500, "Unexpected follow shape");
}

/**
 * Backend-to-port mapping for profiles, isolated here.
 * Rejects anything that is not a well-formed ProfileView.
 */
function mapProfile(raw: unknown): ProfileView {
  if (
    raw !== null &&
    typeof raw === "object" &&
    typeof (raw as { following?: unknown }).following === "boolean" &&
    typeof (raw as { followersCount?: unknown }).followersCount === "number" &&
    typeof (raw as { followingCount?: unknown }).followingCount === "number"
  ) {
    return {
      user: mapUser((raw as { user?: unknown }).user),
      following: (raw as { following: boolean }).following,
      followersCount: (raw as { followersCount: number }).followersCount,
      followingCount: (raw as { followingCount: number }).followingCount,
    };
  }
  throw new ApiError(500, "Unexpected profile shape");
}

/**
 * Live fetch adapter. Cookie sessions only: every request uses
 * `credentials: "include"` and never sends an `Authorization` header.
 * Never import this outside `lib/composition.ts` — pages use the gateway
 * from context.
 */
export function createBackendGateway(
  baseUrl: string,
  hooks: GatewayHooks = {},
): BackendGateway {
  const cleanBase = baseUrl.replace(/\/+$/, "");

  async function request<T>(
    path: string,
    init: RequestInit,
    options?: { suppressSessionEnd?: boolean },
  ): Promise<T> {
    const res = await fetch(`${cleanBase}${path}`, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
    if (res.status === 401) {
      const error = await parseError(res);
      // Login-scoped suppression: the login 401 is form input feedback
      // (wrong password), never a session end. All other requests keep
      // the central 401 → clear + /login wiring.
      if (!options?.suppressSessionEnd) hooks.onSessionEnd?.();
      throw new ApiError(401, error.detail ?? "Unauthenticated", error);
    }
    if (!res.ok) {
      const error = await parseError(res);
      throw new ApiError(res.status, error.detail ?? res.statusText, error);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  return {
    async register(input: RegisterInput): Promise<RegistrationResult> {
      const raw = await request<unknown>("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          email: input.email,
          username: input.username,
          display_name: input.displayName,
          password: input.password,
        }),
      });
      return mapRegistration(raw);
    },
    /**
     * POST /auth/login over the cookie session. The backend answers 204
     * empty, so success resolves without parsing a body. A 401 here is
     * form feedback (invalid_credentials) and never fires the central
     * session end — the form owns the error. 403 origin_not_allowed
     * passes through untouched — it is an origin denial, not a session end.
     */
    async login(input: LoginInput): Promise<void> {
      await request<unknown>(
        "/auth/login",
        {
          method: "POST",
          body: JSON.stringify({
            email: input.email,
            password: input.password,
          }),
        },
        { suppressSessionEnd: true },
      );
    },
    /**
     * GET /auth/me over the cookie session. No suppression: a 401 keeps
     * the central session-end wiring and surfaces ApiError(401)
     * unauthenticated — callers decide (login-form treats it as failure,
     * the shell treats it as signed-out).
     */
    async me(): Promise<User> {
      const raw = await request<unknown>("/auth/me", { method: "GET" });
      return mapUser(raw);
    },
    async logout(): Promise<void> {
      await request<unknown>("/auth/logout", {
        method: "POST",
        body: JSON.stringify({}),
      });
      hooks.onSessionEnd?.();
    },
    async createTweet(input: PostTweetInput): Promise<Tweet> {
      const raw = await request<unknown>("/tweet", {
        method: "POST",
        body: JSON.stringify(input),
      });
      return mapTweet(raw);
    },
    async timeline(): Promise<Tweet[]> {
      const raw = await request<unknown>("/tweet", { method: "GET" });
      if (!Array.isArray(raw))
        throw new ApiError(500, "Unexpected tweet shape");
      return raw.map(mapTweet);
    },
    async profile(username: string): Promise<ProfileView> {
      const raw = await request<unknown>(
        `/profile/${encodeURIComponent(username)}`,
        { method: "GET" },
      );
      return mapProfile(raw);
    },
    async setFollow(input: ToggleFollowInput): Promise<FollowState> {
      const raw = await request<unknown>("/follow", {
        method: "POST",
        body: JSON.stringify(input),
      });
      return mapFollowState(raw);
    },
  };
}

export { ApiError };
