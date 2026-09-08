"use client";

import { SquarePen } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";
import { useApp } from "@/app/providers";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { TweetBox } from "@/features/tweets/tweet-box";
import { ApiError } from "@/lib/api/port";

interface ComposerContextValue {
  /** Opens the global composer Dialog (shell New-post trigger). */
  openComposer: () => void;
  /** Bumps on every successful Dialog post; feed owners reload on change. */
  postedToken: number;
}

const ComposerContext = createContext<ComposerContextValue | null>(null);

export function useComposer(): ComposerContextValue {
  const ctx = useContext(ComposerContext);
  if (ctx === null)
    throw new Error("useComposer must be used within ComposerProvider");
  return ctx;
}

interface ComposerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPosted: () => void;
}

/**
 * Global composer Dialog: reuses the single TweetBox post path (280
 * strip-check, 422/401 handling) instead of forking a second composer.
 * Success invalidates the current feed via onPosted, closes, and toasts;
 * a 401 also closes — the central 401 wiring is already routing to /login.
 */
function ComposerDialog({ open, onOpenChange, onPosted }: ComposerDialogProps) {
  const { gateway } = useApp();

  async function onPost(text: string): Promise<unknown> {
    try {
      const created = await gateway.createTweet({ text });
      onPosted();
      onOpenChange(false);
      toast.success("Posted");
      return created;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onOpenChange(false);
      }
      throw err;
    }
  }

  return (
    <Dialog
      open={open} onOpenChange={onOpenChange}>
      <DialogContent >
        <DialogHeader>
          <DialogTitle>New post</DialogTitle>
        </DialogHeader>
        <TweetBox id="composer-dialog-input" onPost={onPost} />
      </DialogContent>
    </Dialog>
  );
}

/** Shell header trigger: opens the global composer Dialog. */
export function NewPostButton() {
  const { openComposer } = useComposer();
  return (
    <Button type="button" onClick={openComposer} className="ml-auto">
      <SquarePen data-icon="inline-start" />
      New post
    </Button>
  );
}

/**
 * Mounted once in the shell layout around the header trigger and the
 * outlet: owns the Dialog open state plus the posted token that feed
 * owners (Home today) subscribe to for invalidation.
 */
export function ComposerProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [postedToken, setPostedToken] = useState(0);
  const openComposer = useCallback(() => setOpen(true), []);
  const handlePosted = useCallback(
    () => setPostedToken((token) => token + 1),
    [],
  );
  const value = useMemo(
    () => ({ openComposer, postedToken }),
    [openComposer, postedToken],
  );

  return (
    <ComposerContext.Provider value={value}>
      {children}
      <ComposerDialog
        open={open}
        onOpenChange={setOpen}
        onPosted={handlePosted}
      />
    </ComposerContext.Provider>
  );
}
