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
- Env source: root `.env.example` (not `frontend/.env.example`);
  `NEXT_PUBLIC_API_URL` is the browser backend URL.
- Tests: mock HTTP with MSW; no live backend in tests.
- Styling: Tailwind v4 mobile-first (`sm:md:lg:` scale up from mobile);
  shadcn installed over `@base-ui/react` primitives — keep components shadcn-compatible.
  (email for login).
- Auth (Option A, PROVISIONAL): `POST /auth/login` returns User +
  `Set-Cookie: session`; `credentials: include`, never Authorization;
  memory + PUBLIC-only sessionStorage mirror; any 401 clears and
  routes `/login`; `POST /auth/logout`.
- Tweets (S2): `/` owns the timeline and composer; the client blocks text
  over 280 characters, while the server remains authoritative with 422.
- Social (S3): `/profile/[username]` owns follow/unfollow and updates the
  profile count; shell header owns user search (`GET /users/search`) and
  navigates to profiles — do not add follow affordances outside profile.
- Arch: single `BackendGateway` port (`lib/api`), one fetch adapter,
  `lib/composition.ts` factory-called-once, no fetch outside adapter;
  `features/*` smart slices own UI+hooks, `components/*` dumb only.
- Tooling: pnpm only (10.32.1 via corepack); dev runs Turbopack
  (`pnpm dev --turbopack`).
- Tests: `pnpm vitest run` with MSW (`onUnhandledRequest: error`,
  zero live HTTP) + RTL; jsdom needs `matchMedia` shim.
- Prod image uses `output: 'standalone'` in next.config.ts (enabled).
