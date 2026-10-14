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
- **Stage 4, candidates:** 1 to 100 fictional candidates per vacancy. Code samples who each candidate is (with a known match category, as ground truth) and builds their dated job history; the model writes the CV prose. A searchable, sortable candidate page with a CV view. Tested with a fake model only.
- **Stage 5, selection script:** the model proposes screening criteria from the vacancy text: keywords (with alternatives), years, hard or soft, and the sentence each one is based on. Code checks that sentence is really in the vacancy. The recruiter edits and submits. Hard and soft requirements are applied in one function.
- **Stage 6, long list and short list:** one screening run produces both. Code finds each script keyword in the anonymised CV, computes years from the dated jobs and applies hard and soft requirements. The model assesses the strongest candidates. Code checks its claims against the CV and removes what is not supported. Names and contact details are joined back only for display. Not yet run against the real model.

### What has run against the real Mistral API

On 2026-10-13, with `mistral-small-2603`, about 80 calls in total:

- six calls through `uv run pytest -m mistral tests/real -s` (one vacancy, one vacancy profile, four CVs);
- two runs of one vacancy and 20 candidates through the app's job pipeline. The first exposed three design faults and produced 16 of 20 candidates. After the fixes, the second produced 20 of 20, every CV usable on the first answer, in 19.5 seconds, for an estimated $0.0075;
- six selection-script proposals, each on a freshly generated vacancy (cloud engineer and district nurse), at an estimated $0.0005 each. Every reason was an exact quote from the vacancy. The grouping of alternatives was not always right.

Total estimated spend: under 3 cents. Every automated test, including the browser tests, uses the fake model. Details and the measured figures are in [cards/04-candidates.md](cards/04-candidates.md) and [cards/05-selection-script.md](cards/05-selection-script.md).

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

uv run pytest -m mistral tests/real -s             # six real Mistral calls (under one cent); needs MISTRAL_API_KEY

npm --prefix web run build                         # the browser tests use the built frontend
uv run playwright install chromium                 # once
uv run pytest -m e2e tests/e2e                     # browser tests: real frontend and backend, fake model

npm --prefix web run lint
npm --prefix web run build      # type check and production build
npm --prefix web test
```

CI (GitHub Actions) runs all of the above on every push to `main` and on pull requests.
