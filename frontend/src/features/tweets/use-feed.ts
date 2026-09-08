"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useApp } from "@/app/providers";
import { ApiError, type Tweet } from "@/lib/api/port";

export interface UseFeedOptions {
  /** 1–50; omitted means the backend default (20). */
  pageSize?: number;
}

export interface UseFeedResult {
  tweets: Tweet[];
  loading: boolean;
  error: string | null;
  reload: () => void;
  hasMore: boolean;
  loadingMore: boolean;
  loadMoreError: string | null;
  loadMore: () => void;
  /** Attach to the sentinel row: IntersectionObserver auto-pages. */
  sentinelRef: (node: HTMLElement | null) => void;
  /** Optimistic delete: 204 commits, 403/404/422 roll back with copy. */
  removeTweet: (id: string) => Promise<void>;
  deleteError: string | null;
  pendingDeleteId: string | null;
}

function deleteCopy(status: number): string {
  if (status === 403) return "You can only delete your own posts.";
  if (status === 404) return "That post is already gone.";
  return "Couldn't delete that post. Please try again.";
}

/**
 * P2 shared feed hook (deep module): owns cursor paging, the
 * single-flight guard, and the sentinel observer. Home renders through
 * this; my-profile reuses it with an author filter on the loaded rows.
 * New posts arrive via the global composer Dialog's posted-token reload —
 * this hook owns no post path. Auth failures need no handling here — the
 * fetch adapter clears the session and routes to /login centrally on
 * any 401.
 */
export function useFeed(options: UseFeedOptions = {}): UseFeedResult {
  const { gateway } = useApp();
  const pageSize = options.pageSize;
  const [tweets, setTweets] = useState<Tweet[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null | undefined>(
    undefined,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  /** Single-flight guard: at most one page request in flight. */
  const inFlight = useRef(false);
  /**
   * Synchronous mirror of `tweets` for optimistic deletes: state updaters
   * must stay pure (React may defer or re-invoke them), so the rollback
   * snapshot is read here at call time instead of inside an updater.
   */
  const tweetsRef = useRef<Tweet[]>([]);
  tweetsRef.current = tweets;
  const stateRef = useRef({ nextCursor, loadingMore });
  stateRef.current = { nextCursor, loadingMore };
  const loadMoreRef = useRef(() => {});
  const observerRef = useRef<IntersectionObserver | null>(null);

  // First page (and reloads) deliberately skip the shared single-flight
  // guard: the only triggers are mount and an explicit reload, so no
  // duplicate can self-fire outside StrictMode — and under a StrictMode
  // root double-mount the guard would suppress the second setup while the
  // first run's commit is discarded, sticking `loading` true forever (the
  // Fix-1 invisible-post bug). The per-run `live` flag still drops the
  // stale first response. `loadMore` below keeps the guard: sentinel
  // re-fires are the real duplicate source. (Dev StrictMode therefore
  // issues one redundant first-page GET; the paging discipline is intact.)
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    setLoadMoreError(null);
    gateway
      .feed(pageSize === undefined ? undefined : { pageSize })
      .then((page) => {
        if (!live) return;
        setTweets(page.items);
        setNextCursor(page.nextCursor);
        setLoading(false);
      })
      .catch(() => {
        if (!live) return;
        setError("Couldn't load your feed.");
        setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [gateway, pageSize, reloadToken]);

  const loadMore = useCallback(() => {
    const { nextCursor: cursor, loadingMore: busy } = stateRef.current;
    if (inFlight.current || busy || cursor === null || cursor === undefined) {
      return;
    }
    inFlight.current = true;
    setLoadingMore(true);
    setLoadMoreError(null);
    gateway
      .feed(
        pageSize === undefined ? { cursor } : { pageSize, cursor },
      )
      .then((page) => {
        setTweets((prev) => [...prev, ...page.items]);
        setNextCursor(page.nextCursor);
        setLoadingMore(false);
      })
      .catch(() => {
        setLoadMoreError("Couldn't load more posts.");
        setLoadingMore(false);
      })
      .finally(() => {
        inFlight.current = false;
      });
  }, [gateway, pageSize]);

  loadMoreRef.current = loadMore;

  const sentinelRef = useCallback((node: HTMLElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (node === null) return;
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        loadMoreRef.current();
      }
    });
    observer.observe(node);
    observerRef.current = observer;
  }, []);

  useEffect(() => {
    return () => {
      observerRef.current?.disconnect();
      observerRef.current = null;
    };
  }, []);

  const reload = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  const removeTweet = useCallback(
    async (id: string): Promise<void> => {
      const snapshot = tweetsRef.current;
      setTweets(snapshot.filter((tweet) => tweet.id !== id));
      setDeleteError(null);
      setPendingDeleteId(id);
      try {
        await gateway.deleteTweet(id);
      } catch (err) {
        // 204 never lands here: restore the row and surface copy.
        setTweets(snapshot);
        setDeleteError(
          deleteCopy(err instanceof ApiError ? err.status : 0),
        );
        throw err;
      } finally {
        setPendingDeleteId(null);
      }
    },
    [gateway],
  );

  return {
    tweets,
    loading,
    error,
    reload,
    hasMore: nextCursor !== null && nextCursor !== undefined,
    loadingMore,
    loadMoreError,
    loadMore,
    sentinelRef,
    removeTweet,
    deleteError,
    pendingDeleteId,
  };
}
