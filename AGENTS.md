# iori — project rules

## Git

- **Commits are authored by the user only.** Do NOT add `Co-Authored-By`, `Generated with`, or any other agent/tool trailers or attribution to commit messages. This applies to every commit in every session.
- Commit style: lowercase `phase N: short description` (see `git log`).
- Never commit `.env`, `.env.local`, or secrets.

## Dev commands

- Full stack (Docker): `docker compose up -d` from the repo root — Postgres on :5433 (localhost-bound; `POSTGRES_BIND=0.0.0.0` to expose), backend on :8000 (runs `alembic upgrade head` then `uvicorn --reload`), frontend on :3000 (Next dev, webpack — Turbopack's watcher misses edits through Docker Desktop mounts). Rebuild after dependency changes: `docker compose up -d --build`. Postgres credentials come from `backend/.env` (single source for both services).
- Production: `docker compose -f docker-compose.prod.yml up -d --build` — baked images (`backend/Dockerfile.prod`, `frontend/Dockerfile`), no bind mounts, no `--reload`/`next dev`, non-root users, Postgres not published. Requires `ENVIRONMENT=production` + strong `SECRET_KEY` + non-default credentials in `backend/.env`; `NEXT_PUBLIC_API_URL` is a frontend build arg.
- Backend tests: `docker compose exec backend python -m pytest tests`.
- Frontend checks: `docker compose exec frontend npx tsc --noEmit`, `docker compose exec frontend npx eslint .`, `docker compose exec frontend npm run build`.

## VPS production (139.99.99.169)

- SSH: `ssh -p 22022 ubuntu@139.99.99.169` (key auth only; fail2ban active — verify keys locally before connecting).
- App lives at `~/iori` (git checkout of `JovenWu/iori`, `main`); update with `git pull` then `docker compose -f docker-compose.prod.yml up -d --build`.
- Ports are intentionally loopback-only and non-conflicting with the other prod stacks on this box: frontend `127.0.0.1:3300`, backend `127.0.0.1:8000`, Postgres unpublished. Public ingress (domain/TLS) is layered on by a reverse proxy later.
- API is same-origin: `NEXT_PUBLIC_API_URL=""` in the prod build → browser calls `/api/*` on the frontend → `next.config.ts` rewrites proxy to `http://backend:8000` internally.
- `backend/.env` on the VPS carries production `APP_*`/`POSTGRES_*`/`SECRET_KEY`; it is not the same file as local dev's (dev defaults are rejected by the prod config check).
- Other tenants on the box: ports 80/443 (thesismate/koperasi nginx), 3002, 5432, 5433, 8001, 8080 (traefik devproxy, tailnet), 8151, 9000/9443 (portainer) — do not reuse.

## Conventions

- After making code changes, always invoke `/code-simplifier` to audit and refine them before finishing.
- Design rules live in `DESIGN.md`; product intent in `PRODUCT.md`.
- Dark canvas + teal accent; no warm/bright/yellow accents; dark-first theming.

## Active feature — Aksi Korporasi Copilot (phase 14)

- Spec: `docs/superpowers/specs/2026-10-06-aksi-korporasi-design.md`. Plan: `docs/superpowers/plans/2026-10-06-aksi-korporasi.md` — the plan wins where they differ. Build from these only; other idea notes in `docs/` are superseded.
- Never output buy/sell/hold/exercise advice (POJK 6/2026). Every number comes from `backend/app/aksi/calc.py`; the LLM writes placeholders only.
- Sectors credits are scarce: tests mock `app.sectors.client.get`; aksi code never passes `refresh=True`.
- The backend container runs Python 3.10.
