"use client";

import { cn } from "cn";
import { SendIcon } from "lucide-react";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/port";
import {
  canPostTweet,
  TWEET_MAX_LENGTH,
  validateTweetText,
} from "./domain/tweet-policy";

interface TweetBoxProps {
  /** Posts the text (hook-owned); resolves on success, rejects ApiError. */
  onPost: (text: string) => Promise<unknown>;
  className?: string;
  /** Label/textarea id; override when a second instance shares the DOM. */
  id?: string;
}

/**
 * S2 tweet composer. Enforces the 280 rule client-side (button stays
 * disabled until the text is postable) so over-limit posts never reach
 * the network; the server 422 remains the authority for bypasses.
 */
export function TweetBox({ onPost, className, id = "tweet-composer" }: TweetBoxProps) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const validation = validateTweetText(text);
  const overLimit = !validation.ok && validation.reason === "too_long";
  const postable = validation.ok && !pending;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canPostTweet(text) || pending) return;
    setPending(true);
    try {
      await onPost(text);
      setText("");
    } catch (err) {
      const message =
        err instanceof ApiError && err.status === 422
          ? "That post is too long (280 characters max)."
          : "Couldn't post. Please try again.";
      toast.error(message);
    } finally {
      setPending(false);
    }
  }

  return (
    <Card className={cn("py-4", className)}>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={id}>What&apos;s happening?</Label>
            <Textarea
              id={id}
              placeholder="Share what's happening…"
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={3}
            />
          </div>
          <div className="flex items-center justify-between gap-3">
            <span
              aria-live="polite"
              className={cn(
                "text-sm tabular-nums",
                overLimit
                  ? "text-destructive font-medium"
                  : "text-muted-foreground",
              )}
            >
              {text.length} / {TWEET_MAX_LENGTH}
            </span>
            <Button type="submit" disabled={!postable}>
              <SendIcon data-icon="inline-start" />
              {pending ? "Posting…" : "Post"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
