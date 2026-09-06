"use client";

import { cn } from "cn";
import { UserCheckIcon, UserPlusIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

interface FollowButtonProps {
  /** Current follow state for the profile. */
  following: boolean;
  /** True while the toggle request is in flight. */
  pending?: boolean;
  /** Hook-owned toggle; resolves on success, rejects ApiError. */
  onToggle: () => void;
  className?: string;
}

/**
 * S3 follow toggle. Dumb display: the label flips immediately from the
 * hook's updated profile, so no local state lives here.
 */
export function FollowButton({
  following,
  pending = false,
  onToggle,
  className,
}: FollowButtonProps) {
  return (
    <Button
      type="button"
      variant={following ? "outline" : "default"}
      aria-pressed={following}
      disabled={pending}
      onClick={onToggle}
      className={cn(className)}
    >
      {following ? <UserCheckIcon /> : <UserPlusIcon />}
      {pending ? "Saving…" : following ? "Following" : "Follow"}
    </Button>
  );
}
