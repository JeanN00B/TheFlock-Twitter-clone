"use client";

import { use } from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Card, CardContent } from "@/components/ui/card";
import { useSession } from "@/features/auth/session-store";
import { FollowButton } from "@/features/social/follow-button";
import { useProfile } from "@/features/social/use-profile";

interface ProfilePageProps {
  params: Promise<{ username: string }>;
}

function initialsFor(displayName: string, username: string): string {
  const fromName = displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("");
  return fromName ? fromName.toUpperCase() : username.slice(0, 2).toUpperCase();
}

/** Thin inbound adapter: composes the profile hook + follow button, no logic. */
export default function ProfilePage({ params }: ProfilePageProps) {
  const { username } = use(params);
  const { session } = useSession();
  const { profile, loading, error, toggling, toggleFollow } =
    useProfile(username);
  // Compare the resolved canonical username so URL casing cannot bypass the
  // others-only guard.
  const isSelf =
    session !== null &&
    profile !== null &&
    session.user.username.toLowerCase() === profile.username.toLowerCase();

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-4 sm:p-6">
      <h1 className="text-xl font-bold tracking-tight">Profile</h1>
      {loading ? (
        <p className="text-sm text-muted-foreground">Loading profile…</p>
      ) : null}
      {!loading && error !== null ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {!loading && error === null && profile !== null ? (
        <Card className="py-4">
          <CardContent className="flex items-center gap-4">
            <Avatar size="lg">
              <AvatarFallback>
                {initialsFor(profile.displayName, profile.username)}
              </AvatarFallback>
            </Avatar>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <p className="truncate text-base font-semibold">
                {profile.displayName}
              </p>
              <p className="truncate text-sm text-muted-foreground">
                @{profile.username}
              </p>
              <p
                aria-live="polite"
                className="text-sm text-muted-foreground tabular-nums"
              >
                {`${profile.followersCount} ${profile.followersCount === 1 ? "follower" : "followers"} · ${profile.followingCount} following`}
              </p>
            </div>
            {isSelf ? null : (
              <FollowButton
                following={profile.followedByActor}
                pending={toggling}
                onToggle={toggleFollow}
              />
            )}
          </CardContent>
        </Card>
      ) : null}
    </main>
  );
}
