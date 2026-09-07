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

  it("valid credentials establish the cookie session and navigate home", async () => {
    renderLogin();
    submit("alice@example.com", "password123");

    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    // Backend answers 204 empty: identity lives in the httpOnly cookie,
    // so nothing user-visible is mirrored to sessionStorage.
    expect(__getAuthStandIn()).toContain("flock_session=");
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it("401 stays signed out with an error and nothing persisted", async () => {
    renderLogin();
    submit("alice@example.com", "wrong");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
      "Invalid email or password.",
    ));
    expect(screen.getByTestId("session")).toHaveTextContent("empty");
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(push).not.toHaveBeenCalledWith("/");
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

  it("stale/expired/revoked 401 clears the mirror and redirects to /login", async () => {
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ user: alice }),
    );
    renderLogin();
    expect(screen.getByTestId("session")).toHaveTextContent("alice");

    submit("alice@example.com", "wrong");

    await waitFor(() =>
      expect(screen.getByTestId("session")).toHaveTextContent("empty"),
    );
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(push).toHaveBeenCalledWith("/login");
  });
});
