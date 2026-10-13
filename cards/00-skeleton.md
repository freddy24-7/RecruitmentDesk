# Stage 0: Skeleton

Date: 2026-10-13

## What was built

- Backend: FastAPI app with a `/health` endpoint, typed settings, an async database engine and session factory.
- Database: local PostgreSQL through Docker Compose, Alembic configured for the async engine. There are no tables and no migrations yet.
- Frontend: a Vite app with React and TypeScript that shows the app name and a "fictional candidates" line.
- Checks: `ruff`, `mypy --strict`, `pytest` with a 70% coverage gate, ESLint, TypeScript strict mode, Vitest, and a script that fails when Git tracks a codes file or a `.env` file.
- CI: a GitHub Actions workflow that runs all checks, with PostgreSQL as a service container.

## Decisions and why

- **Real PostgreSQL in tests, not SQLite.** Stage 1 must prove that 25 simultaneous redemptions give exactly one success. That depends on PostgreSQL's row locking, so a different database in tests would prove nothing.
- **Local PostgreSQL on port 5433.** Port 5432 on the development machine is already used by another project's database.
- **The health endpoint does no work.** It does not touch the database or the model, so an uptime monitor can never cause cost. It answers both GET and HEAD, because many monitors send HEAD.
- **The database URL is normalised in the settings.** Railway provides `postgresql://`; the async driver needs `postgresql+asyncpg://`. The settings convert it and strip stray whitespace, so a pasted value with a trailing newline still works.
- **Alembic from the start**, with the URL taken from the application settings, so there is one place that knows where the database is.
- **ESLint instead of oxlint.** The current Vite template ships with oxlint. CLAUDE.md asks for ESLint, so the template's linter was replaced.
- **Versions are pinned by the lock files** (`uv.lock`, `web/package-lock.json`). CI installs with `uv sync --frozen` and `npm ci`, so it uses exactly those versions.
- **Dependencies are added when a stage needs them.** Stage 0 has no Mistral SDK, no logging library and no UI libraries yet.

## What was seen in practice

- 26 backend tests pass locally, with 85% coverage. 2 frontend tests pass. Lint, types and the production build are clean.
- The tracked-files check was tried against a deliberately tracked `codes.txt`: it failed with exit code 1, and passed again after the file was removed.
- The server was started and `/health` returned 200 for both GET and HEAD.
- The migration test (upgrade, downgrade, upgrade) passes, but with zero migrations it only proves that Alembic is wired to the database. It becomes a real test in stage 1.

## Still open

- ~~The CI workflow has not run yet.~~ Closed: it ran green on GitHub for the skeleton commit (`63eed6f`).
- The frontend is not yet served by the backend. In development Vite proxies `/api` and `/health` to the backend. Serving the built frontend from FastAPI comes with the first browser tests (stage 3) and deployment (stage 9).
- The coverage gate covers `app/` and `scripts/`. The frontend has no coverage gate.
