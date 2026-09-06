import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { User } from "@/lib/api/port";
import {
  SESSION_STORAGE_KEY,
  SessionProvider,
  useSession,
} from "./session-store";

const alice: User = {
  id: "u-alice",
  username: "alice",
  bio: "Test user",
  avatarUrl: null,
};

function Probe() {
  const { session, setFromLogin, clear } = useSession();
  return (
    <div>
      <span data-testid="session">
        {session ? session.user.username : "empty"}
      </span>
      <button type="button" onClick={() => setFromLogin(alice)}>
        set
      </button>
      <button type="button" onClick={() => clear()}>
        clear
      </button>
    </div>
  );
}

function renderStore() {
  return render(
    <SessionProvider>
      <Probe />
    </SessionProvider>,
  );
}

beforeEach(() => sessionStorage.clear());

describe("session-store seam (S1)", () => {
  it("set-from-login holds identity in memory plus PUBLIC mirror, no credentials", () => {
    renderStore();
    fireEvent.click(screen.getByText("set"));

    expect(screen.getByTestId("session")).toHaveTextContent("alice");
    const raw = sessionStorage.getItem(SESSION_STORAGE_KEY) ?? "";
    expect(raw).toContain("alice");
    expect(raw).not.toMatch(/password|token|jwt/i);
  });

  it("reload restores PUBLIC identity from the mirror without a probe request", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ user: alice }),
    );

    renderStore();

    expect(screen.getByTestId("session")).toHaveTextContent("alice");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("clear empties memory plus mirror (logout path)", () => {
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ user: alice }),
    );
    renderStore();
    fireEvent.click(screen.getByText("clear"));

    expect(screen.getByTestId("session")).toHaveTextContent("empty");
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });
});
