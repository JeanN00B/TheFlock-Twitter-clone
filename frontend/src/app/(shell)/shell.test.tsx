import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "@/app/login/page";
import { AppProviders } from "@/app/providers";
import { SESSION_STORAGE_KEY, useSession } from "@/features/auth/session-store";
import { createBackendGateway } from "@/lib/api/fetch-client";
import type { User } from "@/lib/api/port";
import { __resetAuthStandIn } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import FeedPage from "./feed/page";
import ShellLayout from "./layout";

const BASE_URL = "http://localhost:8000";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/",
}));

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

function renderShell() {
  return render(
    <AppProviders>
      <ShellLayout>
        <p>outlet child</p>
      </ShellLayout>
      <SessionProbe />
    </AppProviders>,
  );
}

async function loginAsAlice() {
  await createBackendGateway(BASE_URL).login({
    email: "alice@example.com",
    password: "password123",
  });
}

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  __resetAuthStandIn();
});

describe("home shell (P1 shell+gating)", () => {
  it("restores the session via me() and renders sidebar nav + outlet", async () => {
    await loginAsAlice();
    renderShell();

    await waitFor(() =>
      expect(screen.getByTestId("session")).toHaveTextContent("alice"),
    );
    expect(
      screen.getByRole("navigation", { name: /primary/i }),
    ).toBeInTheDocument();
    const home = screen.getByRole("link", { name: /^home$/i });
    expect(home).toHaveAttribute("href", "/");
    expect(home).toHaveAttribute("data-active");
    expect(screen.getByRole("link", { name: /^feed$/i })).toHaveAttribute(
      "href",
      "/feed",
    );
    expect(screen.getByRole("link", { name: /my profile/i })).toHaveAttribute(
      "href",
      "/my-profile",
    );
    // Session footer shows the restored identity.
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("outlet child")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalledWith("/login");
  });

  it("expired session clears the mirror and gates to /login", async () => {
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ user: alice }),
    );
    renderShell();

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(screen.getByTestId("session")).toHaveTextContent("empty");
  });

  it("offers a search affordance and an enabled New-post trigger", async () => {
    renderShell();

    expect(screen.getByLabelText(/search/i)).toHaveAttribute(
      "placeholder",
      "Search by exact username",
    );
    const trigger = screen.getByRole("button", { name: /new post/i });
    expect(trigger).toBeEnabled();
    fireEvent.click(trigger);

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("/login renders outside the shell (no primary nav)", () => {
    render(
      <AppProviders>
        <LoginPage />
      </AppProviders>,
    );

    expect(
      screen.queryByRole("navigation", { name: /primary/i }),
    ).not.toBeInTheDocument();
  });

  it("/feed renders the deferred notice with zero tweet rows", () => {
    render(
      <AppProviders>
        <FeedPage />
      </AppProviders>,
    );

    expect(screen.getByText(/deferred/i)).toBeInTheDocument();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });
});

describe("sidebar account menu + logout (Fix-3)", () => {
  async function openAccountMenu() {
    fireEvent.click(
      await screen.findByRole("button", { name: /account menu/i }),
    );
    return await screen.findByRole("menuitem", { name: /log out/i });
  }

  it("ellipsis menu opens with the account header and Log out", async () => {
    await loginAsAlice();
    renderShell();

    const logoutItem = await openAccountMenu();

    expect(logoutItem).toBeInTheDocument();
    const menu = screen.getByRole("menu");
    expect(menu).toHaveTextContent("Alice");
    expect(menu).toHaveTextContent("@alice");
  });

  it("logout clears the session and navigates to /login", async () => {
    await loginAsAlice();
    renderShell();
    await waitFor(() =>
      expect(screen.getByTestId("session")).toHaveTextContent("alice"),
    );

    fireEvent.click(await openAccountMenu());

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    expect(screen.getByTestId("session")).toHaveTextContent("empty");
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it("logout failure shows an error and keeps the session", async () => {
    server.use(
      http.post("*/auth/logout", () =>
        HttpResponse.json({ error: { code: "boom" } }, { status: 500 }),
      ),
    );
    await loginAsAlice();
    renderShell();
    await waitFor(() =>
      expect(screen.getByTestId("session")).toHaveTextContent("alice"),
    );

    fireEvent.click(await openAccountMenu());

    expect(await screen.findByText(/couldn't log out/i)).toBeInTheDocument();
    expect(screen.getByTestId("session")).toHaveTextContent("alice");
    expect(push).not.toHaveBeenCalledWith("/login");
  });
});
