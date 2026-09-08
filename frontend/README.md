# Frontend

Client-only Next.js 16 app. All data goes through `BackendGateway`
(`src/lib/api`); nothing imports the backend package or touches the database.

## Prerequisites

- Node.js **24**
- pnpm **10.32.1** (`corepack enable && corepack prepare pnpm@10.32.1 --activate`)

Env lives in the **repo-root** `.env.example` (not `frontend/.env.example`).
Only `NEXT_PUBLIC_*` values reach the browser; they are baked at build time.

## Quick start

```bash
# Prefer full stack from repo root:
# docker compose -f docker-compose.dev.yml up --build

cd frontend
pnpm install
pnpm dev --turbopack
```

Open http://localhost:3000. Default API base: `NEXT_PUBLIC_API_URL=http://localhost:8000`.

## Scripts

| Command | Purpose |
|---------|---------|
| `pnpm dev --turbopack` | Dev server |
| `pnpm build` / `pnpm start` | Production build / serve |
| `pnpm test` | Vitest + Testing Library + MSW (`onUnhandledRequest: error`) |
| `pnpm lint` | Biome check |

## Routes

| Path | Behavior |
|------|----------|
| `/login`, `/register` | Public auth |
| `/` | Home — global tweet feed + composer |
| `/feed` | Following-only timeline |
| `/my-profile` | Signed-in user’s profile timeline |
| `/profile/[username]` | Public profile, follow/unfollow, that user’s tweets |

Shell search hits `GET /users/search`. Auth uses httpOnly cookie sessions with
`credentials: include` (no `Authorization` header).

## Architecture notes

- One composition root: `src/lib/composition.ts`
- Smart UI in `src/features/*`; presentational pieces in `src/components/*`
- Mobile-first Tailwind (`sm:` / `md:` / `lg:`); shadcn over Base UI primitives
- Prod image uses `output: 'standalone'` in `next.config.ts`
