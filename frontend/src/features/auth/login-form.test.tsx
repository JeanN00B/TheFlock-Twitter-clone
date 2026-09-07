import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  SESSION_STORAGE_KEY,
  SessionProvider,
  useSession,
} from "@/features/auth/session-store";
import { ApiError, type BackendGateway, type User } from "@/lib/api/port";
import { LoginForm } from "./login-form";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

let mockGateway: BackendGateway;
vi.mock("@/app/providers", () => ({
  useApp: () => ({ gateway: mockGateway }),
}));

const meUser: User = {
  id: "u-alice",
  username: "alice",
  displayName: "Alice",
  createdAt: "2024-01-01T00:00:00.000Z",
  updatedAt: "2024-01-01T00:00:00.000Z",
  bio: null,
  avatarUrl: null,
};

function fakeGateway(overrides?: Partial<BackendGateway>): BackendGateway {
  return {
    register: () => Promise.reject(new Error("not stubbed")),
    login: () => Promise.resolve(),
    logout: () => Promise.resolve(),
    me: () => Promise.resolve(meUser),
    createTweet: () => Promise.reject(new Error("not stubbed")),
    timeline: () => Promise.resolve([]),
    profile: () => Promise.reject(new Error("not stubbed")),
    setFollow: () => Promise.reject(new Error("not stubbed")),
    ...overrides,
  };
}

function SessionProbe() {
  const { session } = useSession();
  return (
    <span data-testid="session">
      {session ? session.user.username : "empty"}
    </span>
  );
}

function renderForm() {
  return render(
    <SessionProvider>
      <LoginForm />
      <SessionProbe />
    </SessionProvider>,
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
  mockGateway = fakeGateway();
});

describe("login-form seam (fake gateway port)", () => {
  it("login success hydrates the session with the me() user, then navigates home", async () => {
    const calls: string[] = [];
    mockGateway = fakeGateway({
      login: async () => {
        calls.push("login");
      },
      me: async () => {
        calls.push("me");
        return meUser;
      },
    });
    renderForm();
    submit("alice@example.com", "password123");

    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    // The 204 login carries no user: identity comes from me(), in order.
    expect(calls).toEqual(["login", "me"]);
    expect(screen.getByTestId("session")).toHaveTextContent("alice");
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBe(
      JSON.stringify({ user: meUser }),
    );
  });

  it("me() failure after a 204 stays on /login with the generic error", async () => {
    mockGateway = fakeGateway({
      me: () => Promise.reject(new ApiError(500, "boom")),
    });
    renderForm();
    submit("alice@example.com", "password123");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
      "Something went wrong. Please try again.",
    ));
    expect(screen.getByTestId("session")).toHaveTextContent("empty");
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(push).not.toHaveBeenCalled();
  });

  it("me() 401 after a 204 shows the generic error, not the credential error", async () => {
    mockGateway = fakeGateway({
      me: () =>
        Promise.reject(
          new ApiError(401, "Unauthenticated", { code: "unauthenticated" }),
        ),
    });
    renderForm();
    submit("alice@example.com", "password123");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
      "Something went wrong. Please try again.",
    ));
    expect(
      screen.queryByText("Invalid email or password."),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("session")).toHaveTextContent("empty");
    expect(push).not.toHaveBeenCalledWith("/");
  });
});
