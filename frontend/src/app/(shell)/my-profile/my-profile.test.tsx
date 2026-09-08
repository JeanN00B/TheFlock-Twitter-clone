import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ShellLayout from "@/app/(shell)/layout";
import { AppProviders } from "@/app/providers";
import { SESSION_STORAGE_KEY } from "@/features/auth/session-store";
import { createBackendGateway } from "@/lib/api/fetch-client";
import type { User } from "@/lib/api/port";
import {
  __resetAuthStandIn,
  __resetFollows,
  __resetTweets,
  __seedTweet,
} from "@/mocks/handlers";
import { server } from "@/mocks/server";
import MyProfilePage from "./page";

const BASE_URL = "http://localhost:8000";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/my-profile",
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

function renderMyProfile() {
  return render(
    <AppProviders>
      <ShellLayout>
        <MyProfilePage />
      </ShellLayout>
    </AppProviders>,
  );
}

function seedSessionMirror() {
  sessionStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({ user: alice }),
  );
}

async function loginAsAlice() {
  await createBackendGateway(BASE_URL).login({
    email: "alice@example.com",
    password: "password123",
  });
}

/**
 * The page's own landmark: SidebarInset also renders a `<main>`, so scope
 * header assertions through the page heading instead of `getByRole("main")`.
 */
async function pageMain(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: "My profile" });
  const main = heading.closest("main");
  if (main === null) throw new Error("My profile heading outside <main>");
  return main;
}

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  __resetAuthStandIn();
  __resetTweets();
  __resetFollows();
});

describe("my-profile (P3 3.2, corrective: header from session)", () => {
  it("self header reads identity from session: display name, handle, member-since — no Follow button, no profile alert", async () => {
    await loginAsAlice();
    seedSessionMirror();
    renderMyProfile();

    const main = await pageMain();
    expect(within(main).getByText("Alice")).toBeInTheDocument();
    expect(within(main).getByText("@alice")).toBeInTheDocument();
    expect(within(main).getByText(/member since/i)).toHaveTextContent(
      new Date("2024-01-01T00:00:00.000Z").toLocaleDateString(),
    );
    expect(
      within(main).queryByRole("alert"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^follow$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^following$/i }),
    ).not.toBeInTheDocument();
  });

  it("regression: tweets render even when GET /profile/:username 404s (header and list are independent)", async () => {
    // The backend has no GET /profile/:username route: force a 404 and the
    // header (session) plus the tweets list (global feed) must still render.
    server.use(
      http.get("*/profile/*", () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "No such user." } },
          { status: 404 },
        ),
      ),
    );
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    await gateway.createTweet({ text: "alice mine despite missing profile" });
    seedSessionMirror();
    renderMyProfile();

    const main = await pageMain();
    expect(within(main).getByText("Alice")).toBeInTheDocument();
    expect(
      await screen.findByText("alice mine despite missing profile"),
    ).toBeInTheDocument();
    expect(
      within(main).queryByRole("alert"),
    ).not.toBeInTheDocument();
  });

  it("session-null shows the restoring state, not an error", async () => {
    render(
      <AppProviders>
        <MyProfilePage />
      </AppProviders>,
    );

    const main = await pageMain();
    expect(
      within(main).getByText(/loading profile/i),
    ).toBeInTheDocument();
    expect(
      within(main).queryByRole("alert"),
    ).not.toBeInTheDocument();
  });

  it("my tweets list filters to own posts with an honest scoping note", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    await gateway.createTweet({ text: "alice mine" });
    __seedTweet({ username: "bob", text: "bob foreign" });
    seedSessionMirror();
    renderMyProfile();

    expect(await screen.findByText("alice mine")).toBeInTheDocument();
    expect(screen.queryByText("bob foreign")).not.toBeInTheDocument();
    expect(screen.getByText(/only your posts/i)).toBeInTheDocument();
  });

  it("dialog post from my-profile appears in my tweets (posted-token invalidation)", async () => {
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    await gateway.createTweet({ text: "older mine" });
    seedSessionMirror();
    renderMyProfile();

    expect(await screen.findByText("older mine")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /new post/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/what's happening/i), {
      target: { value: "fresh mine" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: /^post$/i }),
    );

    // Dialog close proves the POST landed; the posted-token reload then
    // refetches the list — allow the round-trip to settle.
    await waitFor(
      () => expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(
      await screen.findByText("fresh mine", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });
});
