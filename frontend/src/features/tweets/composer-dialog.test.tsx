import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ShellLayout from "@/app/(shell)/layout";
import Home from "@/app/(shell)/page";
import { AppProviders } from "@/app/providers";
import { SESSION_STORAGE_KEY } from "@/features/auth/session-store";
import { createBackendGateway } from "@/lib/api/fetch-client";
import type { User } from "@/lib/api/port";
import { __resetAuthStandIn, __resetTweets } from "@/mocks/handlers";

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

function renderShellHome() {
  return render(
    <AppProviders>
      <ShellLayout>
        <Home />
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

async function openComposer() {
  fireEvent.click(screen.getByRole("button", { name: /new post/i }));
  return await screen.findByRole("dialog");
}

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  __resetAuthStandIn();
  __resetTweets();
});

describe("global composer dialog (Fix-2)", () => {
  it("New post opens the dialog composer", async () => {
    await loginAsAlice();
    seedSessionMirror();
    renderShellHome();

    const dialog = await openComposer();

    expect(within(dialog).getByText("New post")).toBeInTheDocument();
    expect(
      within(dialog).getByLabelText(/what's happening/i),
    ).toBeInTheDocument();
  });

  it("dialog post closes, toasts, and appears in the feed", async () => {
    // Merged from the removed inline composer: the fetch spy proves the
    // single post path still rides the cookie session (credentials include,
    // never Authorization). The spy starts after seeding so only the
    // dialog POST is counted.
    await loginAsAlice();
    const gateway = createBackendGateway(BASE_URL);
    await gateway.createTweet({ text: "older post" });
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const realFetch = globalThis.fetch;
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(
        async (input: Parameters<typeof fetch>[0], init) => {
          calls.push({ url: String(input), init });
          return realFetch(input, init);
        },
      );
    try {
      seedSessionMirror();
      renderShellHome();

      expect(await screen.findByText("older post")).toBeInTheDocument();
      const dialog = await openComposer();

      fireEvent.change(within(dialog).getByLabelText(/what's happening/i), {
        target: { value: "dialog fresh post" },
      });
      fireEvent.click(
        within(dialog).getByRole("button", { name: /^post$/i }),
      );

      await waitFor(() =>
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
      );
      expect(await screen.findByText("dialog fresh post")).toBeInTheDocument();
      expect(await screen.findByText("Posted")).toBeInTheDocument();
      const posts = calls.filter(
        (call) =>
          call.url.includes("/tweets") && call.init?.method === "POST",
      );
      expect(posts).toHaveLength(1);
      expect(posts[0]?.init?.credentials).toBe("include");
      expect(
        new Headers(posts[0]?.init?.headers).get("authorization"),
      ).toBeNull();
    } finally {
      fetchSpy.mockRestore();
    }
  });

  it("over-limit text stays blocked in the dialog (no POST)", async () => {
    const posts: Array<string> = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        if (String(input).includes("/tweets") && init?.method === "POST") {
          posts.push(String(input));
        }
        return realFetch(input, init);
      },
    );
    try {
      await loginAsAlice();
      seedSessionMirror();
      renderShellHome();

      const dialog = await openComposer();
      fireEvent.change(within(dialog).getByLabelText(/what's happening/i), {
        target: { value: "x".repeat(281) },
      });

      expect(
        within(dialog).getByRole("button", { name: /^post$/i }),
      ).toBeDisabled();
      expect(within(dialog).getByText("281 / 280")).toBeInTheDocument();
      expect(posts).toHaveLength(0);
    } finally {
      vi.restoreAllMocks();
    }
  });
});
