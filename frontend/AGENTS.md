<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Frontend rules (client-only)
- Client-only: all data via `NEXT_PUBLIC_API_URL` (dev `http://localhost:8000`);
  never import backend code or touch the DB.
- Env: only `NEXT_PUBLIC_*` vars reach the browser; baked at build time
  (builder `ARG` in `docker/Dockerfile`).
- Tests: mock HTTP with MSW; no live backend in tests.
- Styling: Tailwind v4 mobile-first (`sm:md:lg:` scale up from mobile);
  shadcn planned — keep components shadcn-compatible.
- Tooling: pnpm only (10.32.1 via corepack); dev runs Turbopack
  (`pnpm dev --turbopack`).
- Prod image expects `output: 'standalone'` in next.config.ts
  (NOT enabled yet — dev first).
