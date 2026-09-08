"use client";

import { useEffect, useRef } from "react";
import { FeedList } from "@/features/tweets/feed-list";
import { useComposer } from "@/features/tweets/composer-dialog";
import { TweetBox } from "@/features/tweets/tweet-box";
import { useFeed } from "@/features/tweets/use-feed";

/**
 * Thin inbound adapter: inline composer over the real cursor feed with
 * delete-own. The global composer Dialog (shell New-post) shares the same
 * TweetBox post path; its successes arrive here as a posted-token bump and
 * reload the current feed (the spec invalidation path).
 */
export default function Home() {
  const feed = useFeed();
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
      <h1 className="text-xl font-bold tracking-tight">Home</h1>
      <TweetBox onPost={feed.post} />
      <FeedList feed={feed} />
    </main>
  );
}
