import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SESSION_STORAGE_KEY, useSession } from "@/features/auth/session-store";
import type { User } from "@/lib/api/port";
import {
  __getAuthStandIn,
  __resetAuthStandIn,
  __setLoginOriginAllowed,
} from "@/mocks/handlers";
import { AppProviders } from "../providers";
import LoginPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const alice: User = {
  id: "u-alice",
  username: "alice",
  displayName: "Alice",
  createdAt: "2024-01-01T00:00:00.000Z",
  updatedAt: "2024-01-01T00:00:00.000Z",
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

function submit(email: string, password: string) {
  fireEvent.change(screen.getByLabelText(/email/i), {
    target: { value: email },
  });
  fireEvent.change(screen.getByLabelText(/password/i), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: /log in/i }));
}

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  __resetAuthStandIn();
});

describe("login page seam (S1)", () => {
  it("offers a link to account registration", () => {
    renderLogin();

    expect(
      screen.getByRole("link", { name: /create an account/i }),
    ).toHaveAttribute("href", "/register");
  });

  it("valid credentials hydrate the session via me() and navigate home", async () => {
    renderLogin();
    submit("alice@example.com", "password123");

    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    // Backend answers login with 204 empty: the form hydrates identity with
    // GET /auth/me and mirrors the PUBLIC user only — never credentials,
    // never the backend email (dropped at the adapter boundary).
    expect(__getAuthStandIn()).toContain("flock_session=");
    expect(screen.getByTestId("session")).toHaveTextContent("alice");
    const raw = sessionStorage.getItem(SESSION_STORAGE_KEY) ?? "";
    expect(JSON.parse(raw)).toEqual({
      user: {
        id: "u-alice",
        username: "alice",
        displayName: "Alice",
        createdAt: "2024-01-01T00:00:00.000Z",
        updatedAt: "2024-01-01T00:00:00.000Z",
        bio: null,
        avatarUrl: null,
      },
    });
    expect(raw).not.toContain("alice@example.com");
    expect(raw).not.toMatch(/password|token|jwt/i);
  });

  it("401 shows the form error with no session-end side effect", async () => {
    renderLogin();
    submit("alice@example.com", "wrong");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
      "Invalid email or password.",
    ));
    expect(screen.getByTestId("session")).toHaveTextContent("empty");
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(push).not.toHaveBeenCalledWith("/");
    // Login-scoped suppression: the login 401 must not fire the central
    // session-end (no clear, no redirect to /login under the form's error).
    expect(push).not.toHaveBeenCalledWith("/login");
    expect(push).not.toHaveBeenCalled();
  });

  it("422 surfaces the email field error and stays signed out", async () => {
    renderLogin();
    submit("not-an-email", "password123");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
      "Email is invalid.",
    ));
    expect(screen.getByTestId("session")).toHaveTextContent("empty");
    expect(push).not.toHaveBeenCalledWith("/");
  });

  it("403 origin denial shows an unavailable message and stays signed out", async () => {
    __setLoginOriginAllowed(false);
    try {
      renderLogin();
      submit("alice@example.com", "password123");

      await waitFor(() =>
        expect(screen.getByRole("alert")).toHaveTextContent(
          "Login is currently unavailable. Please try again later.",
        ),
      );
      expect(screen.getByTestId("session")).toHaveTextContent("empty");
      expect(push).not.toHaveBeenCalledWith("/");
    } finally {
      __setLoginOriginAllowed(true);
    }
  });

  it("failed login never clears a stale mirror nor redirects (login owns its 401)", async () => {
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ user: alice }),
    );
    renderLogin();
    expect(screen.getByTestId("session")).toHaveTextContent("alice");

    submit("alice@example.com", "wrong");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
      "Invalid email or password.",
    ));
    // Login-scoped suppression: no central session-end fires, so the stale
    // mirror is left for the next authenticated read to reconcile — the
    // form error is the only outcome.
    expect(screen.getByTestId("session")).toHaveTextContent("alice");
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).not.toBeNull();
    expect(push).not.toHaveBeenCalled();
  });
});
