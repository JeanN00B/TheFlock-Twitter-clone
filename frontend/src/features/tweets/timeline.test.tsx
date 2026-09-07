import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Home from "@/app/page";
import { AppProviders } from "@/app/providers";
import { SESSION_STORAGE_KEY } from "@/features/auth/session-store";
import { createBackendGateway } from "@/lib/api/fetch-client";
import type { User } from "@/lib/api/port";
import { __resetAuthStandIn, __resetTweets } from "@/mocks/handlers";

const BASE_URL = "http://localhost:8000";

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

function renderHome() {
  return render(
    <AppProviders>
      <Home />
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
  __resetTweets();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("tweets seam (S2)", () => {
  it("authenticated timeline shows posted tweets over a cookie session", async () => {
    await loginAsAlice();
    await createBackendGateway(BASE_URL).createTweet({ text: "seeded hello" });
    renderHome();

    expect(await screen.findByText("seeded hello")).toBeInTheDocument();
    expect(screen.getByText("@alice")).toBeInTheDocument();
  });

  it("280 chars posts over the cookie session and appears, never Authorization", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        calls.push({ url: String(input), init });
        return realFetch(input, init);
      },
    );
    await loginAsAlice();
    renderHome();

    const text = "x".repeat(280);
    fireEvent.change(await screen.findByLabelText(/what's happening/i), {
      target: { value: text },
    });
    fireEvent.click(screen.getByRole("button", { name: /^post$/i }));

    await waitFor(() => expect(screen.getByText(text)).toBeInTheDocument());
    expect(screen.getByLabelText(/what's happening/i)).toHaveValue("");
    const posts = calls.filter(
      (call) => call.url.includes("/tweet") && call.init?.method === "POST",
    );
    expect(posts).toHaveLength(1);
    expect(posts[0]?.init?.credentials).toBe("include");
    expect(
      new Headers(posts[0]?.init?.headers).get("authorization"),
    ).toBeNull();
  });

  it("server stays authority: 281 chars rejects with 422", async () => {
    const gateway = createBackendGateway(BASE_URL);
    await loginAsAlice();

    await expect(
      gateway.createTweet({ text: "x".repeat(281) }),
    ).rejects.toMatchObject({ status: 422 });
    await expect(gateway.createTweet({ text: "   " })).rejects.toMatchObject({
      status: 422,
    });
  });

  it("281 chars never leaves the client (button disabled, no POST /tweet)", async () => {
    const posts: Array<string> = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: Parameters<typeof fetch>[0], init) => {
        if (String(input).includes("/tweet") && init?.method === "POST") {
          posts.push(String(input));
        }
        return realFetch(input, init);
      },
    );
    await loginAsAlice();
    renderHome();

    fireEvent.change(await screen.findByLabelText(/what's happening/i), {
      target: { value: "x".repeat(281) },
    });

    expect(screen.getByRole("button", { name: /^post$/i })).toBeDisabled();
    await waitFor(() =>
      expect(screen.getByText("281 / 280")).toBeInTheDocument(),
    );
    expect(posts).toHaveLength(0);
  });

  it("logged-out timeline 401 clears the mirror and routes to /login", async () => {
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ user: alice }),
    );
    renderHome();

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });
});
