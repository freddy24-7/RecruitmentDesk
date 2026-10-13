# RecruitDesk

A demo web app that shows how an LLM (Mistral) can support the first stages of recruitment: writing a vacancy, creating fictional candidates, turning the vacancy into screening criteria, proposing a long list and short list with a reason per candidate, and preparing interview questions.

**This is a demo, not a product.** All candidates are fictional. Nothing here should be used to make real hiring decisions.

The full specification is in [docs/PRD.md](docs/PRD.md). Notes per stage are in [cards/](cards/).

## Status

Built in ten stages (PRD section 13). Done so far:

- **Stage 0, skeleton:** backend with a health endpoint, database and migration setup, an empty frontend, tests and CI. No model calls and no features yet.

## Run it locally

Requirements: [uv](https://docs.astral.sh/uv/), Node.js 20 or newer, Docker.

```bash
uv sync                                  # Python dependencies
docker compose up -d --wait              # PostgreSQL on localhost:5433
uv run alembic upgrade head              # migrations
uv run uvicorn app.main:app --reload     # backend on http://localhost:8000

npm --prefix web install
npm --prefix web run dev                 # frontend on http://localhost:5173
```

Configuration is read from environment variables. Copy `.env.example` to `.env` to change the defaults. Never commit `.env`.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy .
uv run pytest tests/unit tests/integration --cov --cov-fail-under=70   # needs the local PostgreSQL
uv run python scripts/check_tracked_files.py    # no access codes or .env files tracked by Git

npm --prefix web run lint
npm --prefix web run build      # type check and production build
npm --prefix web test
```

CI (GitHub Actions) runs all of the above on every push to `main` and on pull requests.
