import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "@/app/login/page";
import { AppProviders } from "@/app/providers";
import { SESSION_STORAGE_KEY, useSession } from "@/features/auth/session-store";
import { createBackendGateway } from "@/lib/api/fetch-client";
import type { User } from "@/lib/api/port";
import { __resetAuthStandIn, __resetFollows, __seedTweet } from "@/mocks/handlers";
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
  __resetFollows();
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

  it("offers no search affordance and an enabled New-post trigger", async () => {
    renderShell();

    // Search was removed: no backend search/lookup endpoint exists, so the
    // shell ships no search slot at all (not even a dead input).
    expect(screen.queryByRole("search")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/search/i)).not.toBeInTheDocument();
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

  it("/feed renders following-scoped posts, not the global list", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();
    await gateway.createTweet({ text: "alice own" });
    __seedTweet({ username: "bob", text: "bob followed post" });
    __seedTweet({ username: "carol", text: "carol unrelated" });
    await gateway.setFollow({ username: "bob", following: true });
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ user: alice }),
    );

    const urls: string[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        urls.push(String(input));
        return realFetch(input, init);
      },
    );

    render(
      <AppProviders>
        <ShellLayout>
          <FeedPage />
        </ShellLayout>
      </AppProviders>,
    );

    expect(await screen.findByText("bob followed post")).toBeInTheDocument();
    expect(screen.queryByText("alice own")).not.toBeInTheDocument();
    expect(screen.queryByText("carol unrelated")).not.toBeInTheDocument();
    expect(screen.queryByText(/deferred/i)).not.toBeInTheDocument();

    const feedUrl = new URL(
      urls.find((url) => url.includes("/tweets")) ?? "",
    );
    expect(feedUrl.searchParams.get("feed")).toBe("following");
    expect(feedUrl.searchParams.has("username")).toBe(false);
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

  it("account menu links to My profile (P3 3.2 unblocks the omission)", async () => {
    await loginAsAlice();
    renderShell();

    await openAccountMenu();
    fireEvent.click(
      await screen.findByRole("menuitem", { name: /^profile$/i }),
    );

    expect(push).toHaveBeenCalledWith("/my-profile");
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
