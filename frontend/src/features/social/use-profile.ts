"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useApp } from "@/app/providers";
import type { ProfileView } from "@/lib/api/port";

/**
 * S3 profile slice: loads `GET /profile/:username` and applies
 * `POST /follow` results directly, so the button and the follower
 * count reflect the toggle immediately without a refetch.
 * Auth failures need no handling here — the fetch adapter clears the
 * session and routes to /login centrally on any 401.
 */
export function useProfile(username: string) {
  const { gateway } = useApp();
  const [profile, setProfile] = useState<ProfileView | null>(null);
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
      .catch(() => {
        if (!live) return;
        setError("Couldn't load this profile.");
        setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [gateway, username]);

  const toggleFollow = useCallback(async (): Promise<void> => {
    if (profile === null || toggling) return;
    setToggling(true);
    try {
      const next = await gateway.setFollow({
        username: profile.user.username,
        following: !profile.following,
      });
      setProfile((prev) =>
        prev === null
          ? prev
          : {
              ...prev,
              following: next.following,
              followersCount: next.followersCount,
            },
      );
    } catch {
      toast.error("Couldn't update the follow. Please try again.");
    } finally {
      setToggling(false);
    }
  }, [gateway, profile, toggling]);

  return { profile, loading, error, toggling, toggleFollow };
}
