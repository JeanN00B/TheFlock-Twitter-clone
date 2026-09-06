"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import type { SessionView, User } from "@/lib/api/port";

/**
 * PUBLIC-only sessionStorage mirror key. Holds the login `User` object for
 * reload restores only — never credentials (no JWT, no tokens, no keys).
 */
export const SESSION_STORAGE_KEY = "flock.session";

interface SessionApi {
  session: SessionView;
  /** Establish identity from a successful login (memory + PUBLIC mirror). */
  setFromLogin: (user: User) => void;
  /** Clear identity from memory plus mirror (401 guard, logout). */
  clear: () => void;
}

const SessionContext = createContext<SessionApi | null>(null);

function readMirror(): SessionView {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      "user" in parsed &&
      (parsed as { user: unknown }).user !== null &&
      typeof (parsed as { user: { username?: unknown } }).user === "object" &&
      typeof (parsed as { user: { username?: unknown } }).user.username ===
        "string"
    ) {
      return parsed as SessionView;
    }
  } catch {
    // Corrupt mirror heals itself: treat as signed out, clear lazily on write.
  }
  return null;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionView>(readMirror);

  const setFromLogin = useCallback((user: User) => {
    const next: SessionView = { user };
    setSession(next);
    try {
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Storage full/blocked: memory identity still holds for this tab.
    }
  }, []);

  const clear = useCallback(() => {
    setSession(null);
    try {
      window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
    } catch {
      // Already gone or blocked — memory state is the authority.
    }
  }, []);

  const value = useMemo(
    () => ({ session, setFromLogin, clear }),
    [session, setFromLogin, clear],
  );
  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionApi {
  const ctx = useContext(SessionContext);
  if (ctx === null)
    throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
