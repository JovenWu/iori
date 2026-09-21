# Sectors Agent — project rules

## Git

- **Commits are authored by the user only.** Do NOT add `Co-Authored-By`, `Generated with`, or any other agent/tool trailers or attribution to commit messages. This applies to every commit in every session.
- Commit style: lowercase `phase N: short description` (see `git log`).
- Never commit `.env`, `.env.local`, or secrets.

## Dev commands

- Backend: `backend/run.py` with the project venv — `D:\Joven Kuliah\Hackhathon\Sectors-3.0\.venv\Scripts\python.exe run.py` from `backend/`. This entrypoint pins the Windows selector event loop (required by the psycopg checkpointer pool — plain `uvicorn` crashes on Windows). Serves on :8000.
- Frontend: `npm run dev` in `frontend/` (Next.js, Turbopack) on :3000.
- Backend tests: `D:\Joven Kuliah\Hackhathon\Sectors-3.0\.venv\Scripts\python.exe -m pytest backend/tests` — the system `python` lacks `typesafe_sdk`.
- Frontend checks: `npx tsc --noEmit`, `npx next lint`, `npm run build` in `frontend/`.

## Conventions

- After making code changes, always invoke `/code-simplifier` to audit and refine them before finishing.
- Design rules live in `DESIGN.md`; product intent in `PRODUCT.md`.
- Dark canvas + lavender accent; no bright/yellow accents; dark-first theming.
