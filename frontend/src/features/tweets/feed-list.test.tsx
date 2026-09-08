import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppProviders } from "@/app/providers";
import { SESSION_STORAGE_KEY } from "@/features/auth/session-store";
import type { Tweet } from "@/lib/api/port";
import { FeedList } from "./feed-list";
import type { UseFeedResult } from "./use-feed";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const aliceTweet: Tweet = {
  id: "11111111-1111-4111-8111-111111111111",
  text: "alice post",
  createdAt: "2024-02-01T00:00:00.000Z",
  author: { id: "u-alice", username: "alice", displayName: "Alice" },
};

const bobTweet: Tweet = {
  id: "22222222-2222-4222-8222-222222222222",
  text: "bob post",
  createdAt: "2024-01-01T00:00:00.000Z",
  author: { id: "u-bob", username: "bob", displayName: "Bob" },
};

function stubFeed(overrides: Partial<UseFeedResult> = {}): UseFeedResult {
  return {
    tweets: [],
    loading: false,
    error: null,
    reload: vi.fn(),
    hasMore: false,
    loadingMore: false,
    loadMoreError: null,
    loadMore: vi.fn(),
    sentinelRef: vi.fn(),
    removeTweet: vi.fn(),
    deleteError: null,
    pendingDeleteId: null,
    ...overrides,
  };
}

function renderList(feed: UseFeedResult) {
  return render(
    <AppProviders>
      <FeedList feed={feed} />
    </AppProviders>,
  );
}

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  sessionStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({
      user: {
        id: "u-alice",
        username: "alice",
        displayName: "Alice",
        createdAt: "2024-01-01T00:00:00.000Z",
        updatedAt: "2024-01-01T00:00:00.000Z",
        bio: "Test user",
        avatarUrl: null,
      },
    }),
  );
});

describe("FeedList (P2)", () => {
  it("renders rows with author identity and time", () => {
    renderList(stubFeed({ tweets: [aliceTweet, bobTweet] }));

    expect(screen.getByText("alice post")).toBeInTheDocument();
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("bob post")).toBeInTheDocument();
  });

  it("shows the delete button only on own rows", () => {
    renderList(stubFeed({ tweets: [aliceTweet, bobTweet] }));

    expect(
      screen.getByRole("button", { name: /delete post by @alice/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /delete post by @bob/i }),
    ).not.toBeInTheDocument();
  });

  it("shows no delete buttons when signed out", () => {
    sessionStorage.clear();
    renderList(stubFeed({ tweets: [aliceTweet] }));

    expect(
      screen.queryByRole("button", { name: /delete post/i }),
    ).not.toBeInTheDocument();
  });

  it("renders skeleton rows while loading", () => {
    renderList(stubFeed({ loading: true }));

    expect(screen.getByRole("status")).toHaveAttribute(
      "aria-label",
      "Loading your feed",
    );
  });

  it("renders the initial error with a reload action", () => {
    const reload = vi.fn();
    renderList(stubFeed({ error: "Couldn't load your feed.", reload }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn't load your feed.",
    );
    screen.getByRole("button", { name: /try again/i }).click();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("renders retry preserving rows on page errors", () => {
    const loadMore = vi.fn();
    renderList(
      stubFeed({
        tweets: [aliceTweet],
        hasMore: true,
        loadMoreError: "Couldn't load more posts.",
        loadMore,
      }),
    );

    expect(screen.getByText("alice post")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn't load more posts.",
    );
    screen.getByRole("button", { name: /try again/i }).click();
    expect(loadMore).toHaveBeenCalledTimes(1);
  });

  it("renders Load more as the sentinel fallback", () => {
    const loadMore = vi.fn();
    const sentinelRef = vi.fn();
    renderList(stubFeed({ hasMore: true, loadMore, sentinelRef }));

    screen.getByRole("button", { name: /load more/i }).click();
    expect(loadMore).toHaveBeenCalledTimes(1);
  });

  it("renders caught-up only at the null cursor with rows", () => {
    const { rerender } = render(
      <AppProviders>
        <FeedList feed={stubFeed({ tweets: [aliceTweet], hasMore: false })} />
      </AppProviders>,
    );
    expect(screen.getByText(/you're caught up/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /load more/i }),
    ).not.toBeInTheDocument();

    rerender(
      <AppProviders>
        <FeedList feed={stubFeed({ tweets: [], hasMore: false })} />
      </AppProviders>,
    );
    expect(screen.queryByText(/you're caught up/i)).not.toBeInTheDocument();
    expect(screen.getByText(/no posts yet/i)).toBeInTheDocument();
  });

  it("renders delete rollback copy when present", () => {
    renderList(
      stubFeed({
        tweets: [aliceTweet],
        deleteError: "You can only delete your own posts.",
      }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "You can only delete your own posts.",
    );
    expect(screen.getByText("alice post")).toBeInTheDocument();
  });
});
