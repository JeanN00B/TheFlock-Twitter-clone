import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SESSION_STORAGE_KEY, useSession } from "@/features/auth/session-store";
import type { User } from "@/lib/api/port";
import { AppProviders } from "../providers";
import LoginPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const alice: User = {
  id: "u-alice",
  username: "alice",
  bio: "Test user",
  avatarUrl: null,
};

function SessionProbe() {
  const { session } = useSession();
  return (
    <span data-testid="session">
      {session ? session.user.username : "empty"}
    </span>
  );
}

function renderLogin() {
  return render(
    <AppProviders>
      <LoginPage />
      <SessionProbe />
    </AppProviders>,
  );
}

function submit(username: string, password: string) {
  fireEvent.change(screen.getByLabelText(/username/i), {
    target: { value: username },
  });
  fireEvent.change(screen.getByLabelText(/password/i), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: /log in/i }));
}

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
});

describe("login page seam (S1)", () => {
  it("offers a link to account registration", () => {
    renderLogin();

    expect(
      screen.getByRole("link", { name: /create an account/i }),
    ).toHaveAttribute("href", "/register");
  });

  it("valid credentials establish the session and navigate home", async () => {
    renderLogin();
    submit("alice", "password123");

    await waitFor(() =>
      expect(screen.getByTestId("session")).toHaveTextContent("alice"),
    );
    expect(push).toHaveBeenCalledWith("/");
  });

  it("401 stays signed out with an error and nothing persisted", async () => {
    renderLogin();
    submit("alice", "wrong");

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByTestId("session")).toHaveTextContent("empty");
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(push).not.toHaveBeenCalledWith("/");
  });

  it("stale/expired/revoked 401 clears the mirror and redirects to /login", async () => {
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ user: alice }),
    );
    renderLogin();
    expect(screen.getByTestId("session")).toHaveTextContent("alice");

    submit("alice", "wrong");

    await waitFor(() =>
      expect(screen.getByTestId("session")).toHaveTextContent("empty"),
    );
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(push).toHaveBeenCalledWith("/login");
  });
});
