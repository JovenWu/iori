# Sectors Agent — project rules

## Git

- **Commits are authored by the user only.** Do NOT add `Co-Authored-By`, `Generated with`, or any other agent/tool trailers or attribution to commit messages. This applies to every commit in every session.
- Commit style: lowercase `phase N: short description` (see `git log`).
- Never commit `.env`, `.env.local`, or secrets.

## Dev commands

- Full stack (Docker): `docker compose up -d` from the repo root — Postgres on :5433, backend on :8000 (runs `alembic upgrade head` then `uvicorn --reload`), frontend on :3000 (Next dev, webpack — Turbopack's watcher misses edits through Docker Desktop mounts). Rebuild after dependency changes: `docker compose up -d --build`.
- Backend tests: `docker compose exec backend python -m pytest tests`.
- Frontend checks: `docker compose exec frontend npx tsc --noEmit`, `docker compose exec frontend npx eslint .`, `docker compose exec frontend npm run build`.

## Conventions

- After making code changes, always invoke `/code-simplifier` to audit and refine them before finishing.
- Design rules live in `DESIGN.md`; product intent in `PRODUCT.md`.
- Dark canvas + lavender accent; no bright/yellow accents; dark-first theming.
