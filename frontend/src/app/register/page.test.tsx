import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SESSION_STORAGE_KEY, useSession } from "@/features/auth/session-store";
import {
  __getAuthStandIn,
  __resetAuthStandIn,
  __resetRegistration,
} from "@/mocks/handlers";
import { AppProviders } from "../providers";
import RegisterPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

function SessionProbe() {
  const { session } = useSession();
  return (
    <span data-testid="session">
      {session ? session.user.username : "empty"}
    </span>
  );
}

function renderRegister() {
  return render(
    <AppProviders>
      <RegisterPage />
      <SessionProbe />
    </AppProviders>,
  );
}

function fillForm({
  email,
  username,
  displayName,
  password,
}: {
  email: string;
  username: string;
  displayName: string;
  password: string;
}) {
  fireEvent.change(screen.getByLabelText(/email/i), {
    target: { value: email },
  });
  fireEvent.change(screen.getByLabelText(/^username$/i), {
    target: { value: username },
  });
  fireEvent.change(screen.getByLabelText(/display name/i), {
    target: { value: displayName },
  });
  fireEvent.change(screen.getByLabelText(/password/i), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: /create account/i }));
}

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  __resetAuthStandIn();
  __resetRegistration();
});

describe("registration page seam", () => {
  it("shows success, navigates to login, and remains signed out", async () => {
    renderRegister();
    fillForm({
      email: "new@example.com",
      username: "NewUser",
      displayName: " New User ",
      password: "password123",
    });

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    expect(screen.getByRole("status")).toHaveTextContent(/account created/i);
    expect(screen.getByTestId("session")).toHaveTextContent("empty");
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(__getAuthStandIn()).toBeNull();
  });

  it("renders useful field-level validation errors", async () => {
    renderRegister();
    fillForm({
      email: "not-an-email",
      username: "newuser",
      displayName: "New User",
      password: "password123",
    });

    expect(await screen.findByText(/email is invalid/i)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByTestId("session")).toHaveTextContent("empty");
  });

  it("renders both field-level conflict errors", async () => {
    renderRegister();
    fillForm({
      email: "alice@example.com",
      username: "alice",
      displayName: "Alice",
      password: "password123",
    });

    expect(
      await screen.findByText(/email is already in use/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/username is already in use/i)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(__getAuthStandIn()).toBeNull();
  });
});
