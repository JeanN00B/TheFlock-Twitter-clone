"use client";

import { useEffect, useRef } from "react";
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
  // Same profile-scoped feed as /profile/[username]: server filters to this
  // author, cursor paging + sentinel infinite scroll stay in shared FeedList.
  const feed = useFeed({
    scope: { kind: "profile", username: user.username },
  });
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
        <FeedList feed={feed} />
      </section>
    </main>
  );
}

/**
 * Self profile: header from `/auth/me` session identity; posts from the
 * real profile-scoped tweet feed (`feed=profile&username=<me>`), matching
 * public `/profile/[username]` list behavior.
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
