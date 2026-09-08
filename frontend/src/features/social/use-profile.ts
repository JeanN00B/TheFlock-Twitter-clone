"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useApp } from "@/app/providers";
import { ApiError, type PublicProfile } from "@/lib/api/port";

/**
 * P5 profile slice: loads the exact `GET /users/{username}` projection
 * and toggles follow state on the real follow paths
 * (POST/DELETE /users/{username}/follow) via `gateway.setFollow`.
 * The toggle is optimistic — the button flips immediately and rolls back
 * on failure — because the real follow response carries no counts: the
 * ±1 applied here stands on success too. A 404 rolls back with a
 * not-found toast and never ends the session (404 is not 401); auth
 * failures need no handling here — the fetch adapter clears the
 * session and routes to /login centrally on any 401.
 */
export function useProfile(username: string) {
  const { gateway } = useApp();
  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    let live = true;
    setProfile(null);
    setError(null);
    setLoading(true);
    gateway
      .profile(username)
      .then((view) => {
        if (!live) return;
        setProfile(view);
        setLoading(false);
      })
      .catch((error) => {
        if (!live) return;
        setError(
          error instanceof ApiError && error.status === 404
            ? "This user was not found."
            : "Couldn't load this profile.",
        );
        setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [gateway, username]);

  const toggleFollow = useCallback(async (): Promise<void> => {
    if (profile === null || toggling) return;
    const previous = profile;
    const nextFollowing = !profile.followedByActor;
    setProfile({
      ...profile,
      followedByActor: nextFollowing,
      followersCount: Math.max(
        0,
        profile.followersCount + (nextFollowing ? 1 : -1),
      ),
    });
    setToggling(true);
    try {
      const next = await gateway.setFollow({
        username: previous.username,
        following: nextFollowing,
      });
      setProfile((prev) =>
        prev === null ? prev : { ...prev, followedByActor: next.following },
      );
    } catch (error) {
      setProfile(previous);
      if (error instanceof ApiError && error.status === 404) {
        toast.error("This user was not found.");
      } else {
        toast.error("Couldn't update the follow. Please try again.");
      }
    } finally {
      setToggling(false);
    }
  }, [gateway, profile, toggling]);

  return { profile, loading, error, toggling, toggleFollow };
}
