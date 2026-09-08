"use client";

import { Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/features/auth/session-store";
import type { UseFeedResult } from "./use-feed";

interface FeedListProps {
  /** Live feed state owned by `useFeed`; this component renders it only. */
  feed: UseFeedResult;
}

function LoadingRows({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-3">
      {[0, 1, 2].map((key) => (
        <Skeleton key={key} className="h-20 w-full" />
      ))}
    </div>
  );
}

/**
 * P2 home feed list (thin view): renders `useFeed` rows newest-first with
 * sentinel auto-paging plus an explicit Load-more fallback, skeleton /
 * retry / caught-up rows, and delete-own buttons (`author.id == me.id`).
 * No fetch here — all state transitions live in the hook.
 */
export function FeedList({ feed }: FeedListProps) {
  const { session } = useSession();
  const meId = session?.user.id;

  if (feed.loading) return <LoadingRows label="Loading your feed" />;

  return (
    <div className="flex flex-col gap-3">
      {feed.error !== null ? (
        <div className="flex flex-col gap-2">
          <p role="alert" className="text-sm text-destructive">
            {feed.error}
          </p>
          <Button type="button" variant="outline" onClick={feed.reload}>
            Try again
          </Button>
        </div>
      ) : null}
      {feed.deleteError !== null ? (
        <p role="alert" className="text-sm text-destructive">
          {feed.deleteError}
        </p>
      ) : null}
      {feed.error === null && feed.tweets.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No posts yet — be the first to share something.
        </p>
      ) : null}
      <ul className="flex flex-col gap-3">
        {feed.tweets.map((tweet) => {
          const own = meId !== undefined && tweet.author.id === meId;
          const deleting = feed.pendingDeleteId === tweet.id;
          return (
            <li key={tweet.id}>
              <Card className="py-3">
                <CardContent className="flex flex-col gap-1">
                  <p className="text-sm font-medium">
                    {tweet.author.displayName}{" "}
                    <span className="font-normal text-muted-foreground">
                      @{tweet.author.username}
                    </span>
                  </p>
                  <p className="text-sm break-words">{tweet.text}</p>
                  <div className="flex items-center justify-between gap-2">
                    <time
                      dateTime={tweet.createdAt}
                      className="text-xs text-muted-foreground"
                    >
                      {new Date(tweet.createdAt).toLocaleString()}
                    </time>
                    {own ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={deleting}
                        onClick={() => {
                          void feed.removeTweet(tweet.id).catch(() => {});
                        }}
                        aria-label={`Delete post by @${tweet.author.username}`}
                      >
                        <Trash2Icon data-icon="inline-start" />
                        {deleting ? "Deleting…" : "Delete"}
                      </Button>
                    ) : null}
                  </div>
                </CardContent>
              </Card>
            </li>
          );
        })}
      </ul>
      {feed.loadingMore ? <LoadingRows label="Loading more posts" /> : null}
      {feed.loadMoreError !== null ? (
        <div className="flex flex-col gap-2">
          <p role="alert" className="text-sm text-destructive">
            {feed.loadMoreError}
          </p>
          <Button type="button" variant="outline" onClick={feed.loadMore}>
            Try again
          </Button>
        </div>
      ) : null}
      {feed.hasMore ? (
        <div className="flex flex-col gap-2">
          <div ref={feed.sentinelRef} aria-hidden="true" />
          <Button
            type="button"
            variant="outline"
            onClick={feed.loadMore}
            disabled={feed.loadingMore}
          >
            {feed.loadingMore ? "Loading…" : "Load more"}
          </Button>
        </div>
      ) : null}
      {!feed.hasMore && feed.error === null && feed.tweets.length > 0 ? (
        <p className="text-center text-sm text-muted-foreground">
          You&apos;re caught up
        </p>
      ) : null}
    </div>
  );
}
