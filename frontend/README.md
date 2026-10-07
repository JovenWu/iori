# iori frontend

Next.js 16 + React 19 + Tailwind 4 client for the iori backend — chat
with the IDX analysis agent (streamed tool calls, charts, reasoning) plus the
Aksi Korporasi corporate-action page. See the root `README.md` for the full
picture.

## Run

```bash
docker compose up -d   # from the repo root — serves http://localhost:3000
```

Dev runs webpack inside Docker (`WATCHPACK_POLLING`); dependency changes need
`docker compose up -d --build frontend`.

## Checks

```bash
docker compose exec frontend npx tsc --noEmit
docker compose exec frontend npx eslint .
docker compose exec frontend npm run build
```

## Routes

- `/` — chat (new thread)
- `/threads/{id}` — persisted thread with replayed run state
- `/history` — all threads
- `/action` — Aksi Korporasi: holdings, live/replay corporate-action checks
- `/login` — env-credential login

## Conventions

Design tokens and the Spark status system live in `app/globals.css` —
`DESIGN.md` at the repo root documents them. Local state is zustand
(`lib/stores/`); the API client and SSE parsing are in `lib/api.ts`.
