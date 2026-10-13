# RecruitDesk

A demo web app that shows how an LLM (Mistral) can support the first stages of recruitment: writing a vacancy, creating fictional candidates, turning the vacancy into screening criteria, proposing a long list and short list with a reason per candidate, and preparing interview questions.

**This is a demo, not a product.** All candidates are fictional. Nothing here should be used to make real hiring decisions.

The full specification is in [docs/PRD.md](docs/PRD.md). Notes per stage are in [cards/](cards/).

## Status

Built in ten stages (PRD section 13). Done so far:

- **Stage 0, skeleton:** backend with a health endpoint, database and migration setup, an empty frontend, tests and CI.
- **Stage 1, access gate:** nothing is reachable without an access code. Codes are limited to 20 uses, counted atomically, stored only as keyed hashes, and protected against guessing.
- **Stage 2, vacancy generation:** a dialog with a few choices starts a background job; the model writes a vacancy in structured sections. Every model call goes through one module, returns validated JSON, and leaves a usage record. Tested with a fake model only: nothing has run against the real Mistral API yet.
- **Stage 3, review and submit:** a draft is reviewed in an editor, with versions and "Reset to generated". "Cancel vacancy" deletes it after a confirmation that says what is lost. Submitted vacancies get their own list, with actions that are disabled, with a reason, until their prerequisites exist.

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

Before the first run, copy `.env.example` to `.env` and fill in the two secrets (`ACCESS_CODE_PEPPER` and `SESSION_SECRET`). The file explains how to generate them. The app does not start without them. Never commit `.env`.

## The model

`LLM_PROVIDER` in `.env` chooses the model:

- `fake` answers without the network and without cost. Use it for development. Its text is labelled "[Fake model output]".
- `mistral` calls the real Mistral API and costs money. It needs `MISTRAL_API_KEY`.

The model version is pinned in `MISTRAL_MODEL_VACANCY`. A model also needs a price in `app/llm/pricing.py`, or the app refuses to start. Prompts are versioned files in `prompts/`.

Jobs run inside the web process, so run exactly one process (no `--workers`, one replica).

The backend also serves the built frontend from `web/dist` when that folder exists. After `npm --prefix web run build`, the whole app is on http://localhost:8000 without the Vite dev server.

## Access codes

The whole app sits behind an access code. Codes are managed with a script, not a web page:

```bash
uv run python scripts/manage_codes.py create --count 10            # prints the new codes ONCE
uv run python scripts/manage_codes.py status                       # uses per label, never prints codes
uv run python scripts/manage_codes.py extend --label c03 --uses 20
uv run python scripts/manage_codes.py disable --label c03
```

- `create` shows each code once and writes no file. Store the codes in a password manager straight away.
- Codes are stored only as keyed hashes (HMAC-SHA256 with `ACCESS_CODE_PEPPER`). They cannot be recovered from the database, and they stop working if the pepper changes.
- The script acts on the database in `DATABASE_URL` and must use the same pepper as the running app.
- Never put a code in the repository, in an issue, in CI configuration or in a chat.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy .
uv run pytest tests/unit tests/integration --cov --cov-fail-under=70   # needs the local PostgreSQL
                                         # tests use their own database (recruitdesk_test) and fake secrets
uv run python scripts/check_tracked_files.py    # no access codes or .env files tracked by Git

uv run pytest -m mistral tests/real -s             # ONE real Mistral call; costs money, needs MISTRAL_API_KEY

npm --prefix web run build                         # the browser tests use the built frontend
uv run playwright install chromium                 # once
uv run pytest -m e2e tests/e2e                     # browser tests: real frontend and backend, fake model

npm --prefix web run lint
npm --prefix web run build      # type check and production build
npm --prefix web test
```

CI (GitHub Actions) runs all of the above on every push to `main` and on pull requests.
