/**
 * Honest-deferred /feed (P1 route shell): the route + nav contract exist,
 * but the page renders no personal data — zero tweet rows by construction.
 * The real feed lands in a later slice; nothing here is mocked or faked.
 *
 * TODO(near-future refactor): render the personal (following-only) feed once
 * the backend ships a following-feed API (e.g. GET /tweets?feed=following or a
 * dedicated following timeline reusing the existing cursor pagination). Until
 * then this page MUST NOT render the global list as personal data.
 */
export default function FeedPage() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-4 sm:p-6">
      <h1 className="text-xl font-bold tracking-tight">Feed</h1>
      <p className="text-sm text-muted-foreground">
        Feed is deferred — this page intentionally shows no posts yet.
      </p>
    </main>
  );
}
