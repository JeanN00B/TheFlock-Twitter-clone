"use client";

import { useEffect, useMemo, useRef } from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Card, CardContent } from "@/components/ui/card";
import { useSession } from "@/features/auth/session-store";
import { useComposer } from "@/features/tweets/composer-dialog";
import { FeedList } from "@/features/tweets/feed-list";
import { useFeed } from "@/features/tweets/use-feed";
import type { User } from "@/lib/api/port";

/** Same display-name initials as the shell account footer. */
function initialsFor(displayName: string, username: string): string {
  const fromName = displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("");
  if (fromName) return fromName.toUpperCase();
  return username.slice(0, 2).toUpperCase();
}

function MyProfileContent({ user }: { user: User }) {
  const feed = useFeed();
  const { postedToken } = useComposer();
  const firstRender = useRef(true);

  // Same token→reload invalidation as Home: dialog posts made while this
  // page is open reload the list. The mount itself is skipped (useFeed
  // already loads the first page).
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    feed.reload();
  }, [postedToken, feed.reload]);

  // Client-side own-posts filter: the feed seam is global-only, so pages
  // load newest-first across everyone and this view keeps the signed-in
  // author's rows. `hasMore` / Load-more still page the global cursor —
  // the scoping note below says so honestly.
  const myTweets = useMemo(() => {
    return feed.tweets.filter((tweet) => tweet.author.id === user.id);
  }, [feed.tweets, user.id]);

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-4 sm:p-6">
      <h1 className="text-xl font-bold tracking-tight">My profile</h1>
      <Card className="py-4">
        <CardContent className="flex items-center gap-4">
          <Avatar size="lg">
            <AvatarFallback>
              {initialsFor(user.displayName, user.username)}
            </AvatarFallback>
          </Avatar>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <p className="truncate text-base font-semibold">
              {user.displayName}
            </p>
            <p className="truncate text-sm text-muted-foreground">
              @{user.username}
            </p>
            <p className="text-xs text-muted-foreground">
              Member since {new Date(user.createdAt).toLocaleDateString()}
            </p>
          </div>
        </CardContent>
      </Card>
      <section aria-label="My posts" className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Only your posts are listed below, taken from the feed pages loaded
          so far — use Load more to surface older ones of yours.
        </p>
        <FeedList feed={{ ...feed, tweets: myTweets }} />
      </section>
    </main>
  );
}

/**
 * P3 my-profile (self-only, corrective): the header is backend-true /me
 * identity only (displayName, @username, member-since from createdAt).
 * Email stays hidden (PII minimization — the port drops it at the adapter
 * boundary). No bio/avatar/counts/follow here: the backend has no
 * GET /profile/:username route, so this page never calls `profile()`;
 * the header and the tweets list are independent sections — a dead header
 * must never hide tweets again (see the regression test). Others'
 * /profile/[username] keeps its mocked shapes for P4.
 */
export default function MyProfilePage() {
  const { session } = useSession();

  if (session === null) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-4 sm:p-6">
        <h1 className="text-xl font-bold tracking-tight">My profile</h1>
        <p className="text-sm text-muted-foreground">Loading profile…</p>
      </main>
    );
  }
  return <MyProfileContent user={session.user} />;
}
