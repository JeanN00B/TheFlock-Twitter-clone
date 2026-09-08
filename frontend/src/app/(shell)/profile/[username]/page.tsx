"use client";

import { use } from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent } from "@/components/ui/card";
import { useSession } from "@/features/auth/session-store";
import { FollowButton } from "@/features/social/follow-button";
import { useProfile } from "@/features/social/use-profile";

interface ProfilePageProps {
  params: Promise<{ username: string }>;
}

/** Thin inbound adapter: composes the profile hook + follow button, no logic. */
export default function ProfilePage({ params }: ProfilePageProps) {
  const { username } = use(params);
  const { session } = useSession();
  const { profile, loading, error, toggling, toggleFollow } =
    useProfile(username);
  // Follow is others-only: never offer it on your own profile (the
  // backend 422s self-follow; the button must not invite it).
  const isSelf =
    session !== null &&
    session.user.username.toLowerCase() === username.toLowerCase();

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
              {profile.user.avatarUrl !== null ? (
                <AvatarImage
                  src={profile.user.avatarUrl}
                  alt={`@${profile.user.username}`}
                />
              ) : null}
              <AvatarFallback>
                {profile.user.username.slice(0, 1).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <p className="truncate text-base font-semibold">
                @{profile.user.username}
              </p>
              {profile.user.bio !== null ? (
                <p className="text-sm text-muted-foreground">
                  {profile.user.bio}
                </p>
              ) : null}
              <p
                aria-live="polite"
                className="text-sm text-muted-foreground tabular-nums"
              >
                {`${profile.followersCount} ${profile.followersCount === 1 ? "follower" : "followers"} · ${profile.followingCount} following`}
              </p>
            </div>
            {isSelf ? null : (
              <FollowButton
                following={profile.following}
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
