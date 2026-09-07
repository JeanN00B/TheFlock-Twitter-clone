"use client";

import { Card, CardContent } from "@/components/ui/card";
import { TweetBox } from "@/features/tweets/tweet-box";
import { useTimeline } from "@/features/tweets/use-timeline";

/** Thin inbound adapter: composes the timeline hook + composer, no logic. */
export default function Home() {
  const { tweets, loading, error, post } = useTimeline();

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-4 sm:p-6">
      <h1 className="text-xl font-bold tracking-tight">Home</h1>
      <TweetBox onPost={post} />
      {loading ? (
        <p className="text-sm text-muted-foreground">Loading your timeline…</p>
      ) : null}
      {!loading && error !== null ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {!loading && error === null && tweets.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No posts yet — be the first to share something.
        </p>
      ) : null}
      <ul className="flex flex-col gap-3">
        {tweets.map((tweet) => (
          <li key={tweet.id}>
            <Card className="py-3">
              <CardContent className="flex flex-col gap-1">
                <p className="text-sm font-medium">@{tweet.authorUsername}</p>
                <p className="text-sm break-words">{tweet.text}</p>
                <time
                  dateTime={tweet.createdAt}
                  className="text-xs text-muted-foreground"
                >
                  {new Date(tweet.createdAt).toLocaleString()}
                </time>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
    </main>
  );
}
