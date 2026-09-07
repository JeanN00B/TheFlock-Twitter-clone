# FlockTwitter frontend

`frontend/` is a client-only Next.js app. It talks to the backend through the
single `BackendGateway`; it does not import backend code or touch the database.

## Quick start

```bash
cd frontend
pnpm install
pnpm dev --turbopack
```

Open <http://localhost:3000>. The browser API base URL comes from
`NEXT_PUBLIC_API_URL`, configured in the repository-root `.env.example` (the
dev default is `http://localhost:8000`). Only `NEXT_PUBLIC_*` values are
available in browser code and they are baked in at build time.