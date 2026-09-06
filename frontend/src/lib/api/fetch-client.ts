import {
  ApiError,
  type BackendGateway,
  type LoginInput,
  type PostTweetInput,
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

async function parseDetail(res: Response): Promise<string | undefined> {
  try {
    const body: unknown = await res.json();
    if (body !== null && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  } catch {
    // Non-JSON error body — fall back to status text below.
  }
  return undefined;
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

  async function request<T>(path: string, init: RequestInit): Promise<T> {
    const res = await fetch(`${cleanBase}${path}`, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
    if (res.status === 401) {
      hooks.onSessionEnd?.();
      throw new ApiError(401, (await parseDetail(res)) ?? "Unauthenticated");
    }
    if (!res.ok) {
      throw new ApiError(
        res.status,
        (await parseDetail(res)) ?? res.statusText,
      );
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  return {
    login(input: LoginInput): Promise<User> {
      return request<User>("/auth/login", {
        method: "POST",
        body: JSON.stringify(input),
      });
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
  };
}

export { ApiError };
