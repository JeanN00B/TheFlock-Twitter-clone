"use client";

import { useCallback, useEffect, useState } from "react";
import { useApp } from "@/app/providers";
import type { Tweet } from "@/lib/api/port";

/**
 * S2 timeline slice: loads `GET /tweet` once and prepends created tweets.
 * Auth failures need no handling here — the fetch adapter clears the
 * session and routes to /login centrally on any 401.
 */
export function useTimeline() {
  const { gateway } = useApp();
  const [tweets, setTweets] = useState<Tweet[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    gateway
      .timeline()
      .then((rows) => {
        if (!live) return;
        setTweets(rows);
        setLoading(false);
      })
      .catch(() => {
        if (!live) return;
        setError("Couldn't load your timeline.");
        setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [gateway]);

  const post = useCallback(
    async (text: string): Promise<Tweet> => {
      const created = await gateway.createTweet({ text });
      setTweets((prev) => [created, ...prev]);
      return created;
    },
    [gateway],
  );

  return { tweets, loading, error, post };
}
