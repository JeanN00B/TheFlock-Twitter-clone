"use client";

import { useEffect, useRef } from "react";
import { FeedList } from "@/features/tweets/feed-list";
import { useComposer } from "@/features/tweets/composer-dialog";
import { useFeed } from "@/features/tweets/use-feed";

/**
 * Following feed: people the signed-in actor follows, via
 * GET /tweets?feed=following. Home stays on the global/all feed; this
 * route never substitutes that list.
 */
export default function FeedPage() {
  const feed = useFeed({ scope: { kind: "following" } });
  const { postedToken } = useComposer();
  const firstRender = useRef(true);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    feed.reload();
  }, [postedToken, feed.reload]);

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-4 sm:p-6">
      <h1 className="text-xl font-bold tracking-tight">Feed</h1>
      <p className="text-sm text-muted-foreground">
        Posts from people you follow.
      </p>
      <FeedList feed={feed} />
    </main>
  );
}
