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
- **Stage 6, long list and short list:** one screening run produces both. Code finds each script keyword in the anonymised CV, computes years from the dated jobs and applies hard and soft requirements. The model assesses the strongest candidates. Code checks its claims against the CV and removes what is not supported. Names and contact details are joined back only for display. Compared on real pools with the small and the medium model.
- **Stage 7, interview questions:** from the short list, core questions for every candidate and follow-ups per candidate. Each question names the script item, strength or concern it is based on, and code checks that link. Questions that may touch a protected attribute are flagged. Checked on two real pools.
- **Stage 8, evaluation and hardening:** `scripts/evaluate_lists.py` measures the lists against the planted ground truth (precision, recall, evidence accuracy, consistency over repeated runs, a name-swap fairness check, the ranking with facts only, model only and both, and the interview questions: dropped, flagged and reference codes left in the text). A daily spend cap switches generation off when the day's budget is used, one IP address may start at most 5 sessions an hour, idle workspaces are deleted on a timer, "Reset demo" empties a workspace, and large requests are refused. The evaluation ran once against the real API: see below.

### What has run against the real Mistral API

On 2026-10-13 and 14, about 780 calls in total:

- six calls through `uv run pytest -m mistral tests/real -s` (one vacancy, one vacancy profile, four CVs);
- two runs of one vacancy and 20 candidates through the app's job pipeline. The first exposed three design faults and produced 16 of 20 candidates. After the fixes, the second produced 20 of 20, every CV usable on the first answer, in 19.5 seconds, for an estimated $0.0075;
- six selection-script proposals, each on a freshly generated vacancy (cloud engineer and district nurse), at an estimated $0.0005 each. Every reason was an exact quote from the vacancy. The grouping of alternatives was not always right.

- the screening: one pool of 20 assessed by `mistral-small-2603` and by `mistral-medium-2604` (the same lists, at ten times the price for medium), and a second pool after the prompts were revised. Both short lists held only planted strong matches. Between 25% and 37% of the model's claims about keywords and years did not hold and were removed or corrected by the evidence check.

- interview questions on two more fresh pools: every question usable, none dropped, none flagged; a false concern about a missing alternative was found and fixed in the evidence check.

- the evaluation (stage 8), four vacancies of 20 candidates, three screening runs each: 256 calls, $0.156. Short-list precision and long-list recall were 1.00 for all four, with facts only, model only and both; 0 unflagged hard misses; identical lists over repeated runs. Between 27% and 54% of the model's claims about keywords and years were not supported and were removed. Three of four pools lost one or two CVs to timeouts or invalid answers. A first attempt stopped after 206 calls ($0.12) on a timeout and was fixed. Report: [reports/evaluation-20261014-1346-mistral.md](reports/evaluation-20261014-1346-mistral.md).

Total estimated spend: about 54 cents. Every automated test, including the browser tests, uses the fake model. Details and the measured figures are in [cards/04-candidates.md](cards/04-candidates.md), [cards/05-selection-script.md](cards/05-selection-script.md), [cards/06-long-list-and-short-list.md](cards/06-long-list-and-short-list.md), [cards/07-interview-questions.md](cards/07-interview-questions.md) and [cards/08-evaluation-and-hardening.md](cards/08-evaluation-and-hardening.md).

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

## Deployment (Railway)

The app is one Docker image (`Dockerfile`): the built frontend served by the FastAPI backend, on one origin. On start it runs the migrations, then the app (`deploy/start.sh`). Jobs run inside the web process, so it runs as **one replica**.

### Cost

Railway Hobby: $5 a month, which includes $5 of usage. The app and its database need about 0.5 GB of memory together and little CPU, so expect roughly $5 to $10 a month in total ([prices](https://docs.railway.com/reference/pricing/plans)). Mistral is billed separately and is limited by the daily spend cap. **Delete the project when the demo is no longer needed** (see the end of this section).

### Set up (once, in the Railway dashboard)

1. On the Mistral console, set a monthly spending limit (for example $10) and create a **separate API key for production**, so it can be revoked on its own.
2. New project, then **Deploy from GitHub repo** and choose this repository. Railway finds the `Dockerfile` itself.
3. In the project, **add PostgreSQL**.
4. In the app service, under **Settings**:
   - Healthcheck path: `/health`.
   - Replicas: 1. Serverless (sleeping): off, so a visitor never meets a cold start.
   - Restart policy: on failure.
   - Source: deploy on push to `main`, with **Wait for CI** on, so only a commit that passed CI is deployed.
   - Networking: generate a domain.
5. In the app service, under **Variables** (typed in the dashboard, never in the repository or a chat):

   | Variable | Value |
   | --- | --- |
   | `APP_ENV` | `production`. The app then refuses to start without the protections below |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (a reference to the database) |
   | `ACCESS_CODE_PEPPER` | a new secret: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Keep it in a password manager |
   | `SESSION_SECRET` | another new secret, made the same way |
   | `LLM_PROVIDER` | `mistral` |
   | `MISTRAL_API_KEY` | the production key |
   | `DAILY_SPEND_CAP_USD` | `1.00` |
   | `CLIENT_IP_HEADER` | `x-real-ip` (where Railway's edge passes the visitor's address) |
   | `COOKIE_SECURE` | `true` |
   | `CONTACT_URL` | your LinkedIn profile URL |

   The model versions and the limits have defaults in `app/config.py`; `.env.example` lists them all.

### Deploy

Push to `main`. CI runs (including building the image), and Railway then builds and starts the new version. A failed health check keeps the old version running.

### Check the deployment

```bash
uv run python scripts/check_deployment.py https://<app>.up.railway.app             # health, frontend, every API route 401 without a session
uv run python scripts/check_deployment.py https://<app>.up.railway.app --spoofing  # a made-up IP header must not get around the lockout
```

`--spoofing` sends 11 malformed codes, each with a different made-up address in the headers. It must report a lockout: that shows the app counts the address Railway saw, not one a visitor sends. It locks your own address out of the code screen for 15 minutes; then open the app from another network (a phone without wifi) and check that it is **not** locked out. That shows visitors are told apart, not all counted as one.

### Access codes for production

The codes are created from your machine, against the production database, with the production pepper. Use the database's **public** URL (Railway: Postgres service, Variables, `DATABASE_PUBLIC_URL`). Type the values at a hidden prompt, so they do not end up in your shell history:

```bash
read -rs DATABASE_URL && export DATABASE_URL            # paste the public database URL, then Enter
read -rs ACCESS_CODE_PEPPER && export ACCESS_CODE_PEPPER  # paste the production pepper, then Enter
uv run python scripts/manage_codes.py create --count 10   # prints the codes once: into the password manager
uv run python scripts/manage_codes.py status
unset DATABASE_URL ACCESS_CODE_PEPPER
```

### Screenshots

```bash
uv run python scripts/take_screenshots.py https://<app>.up.railway.app   # asks for a code without showing it
```

One walk through the app with 10 candidates: about 22 model calls, roughly 3 cents, and one use of the code. Writes `docs/screenshots/`.

### Operate

- **Stop all generation at once:** set `DAILY_SPEND_CAP_USD` to `0`. Everything else keeps working.
- **A code is abused:** `manage_codes.py disable --label <label>` (as above).
- **Roll back:** in Railway, Deployments, redeploy an earlier deployment. So far every migration only adds tables, indexes and nullable columns, so an earlier version runs on the newer database. A future migration that removes or renames something breaks this; check before rolling back past it.
- **Logs:** Railway, the app service, Logs. They hold ids, counts and error kinds, never CV text, codes or addresses.
- **Spend:** the usage records in the database; the cap counts the same records.

### Remove everything

In Railway: the project, Settings, **Delete project** (this deletes the app and the database with all data). Then revoke the production key on the Mistral console. Nothing else is billed.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy .
uv run pytest tests/unit tests/integration --cov --cov-fail-under=70   # needs the local PostgreSQL
                                         # tests use their own database (recruitdesk_test) and fake secrets
uv run python scripts/check_tracked_files.py    # no access codes or .env files tracked by Git
docker build -t recruitdesk .                   # the image Railway deploys

uv run pytest -m mistral tests/real -s             # six real Mistral calls (under one cent); needs MISTRAL_API_KEY

npm --prefix web run build                         # the browser tests use the built frontend
uv run playwright install chromium                 # once
uv run pytest -m e2e tests/e2e                     # browser tests: real frontend and backend, fake model

npm --prefix web run lint
npm --prefix web run build      # type check and production build
npm --prefix web test
```

CI (GitHub Actions) runs all of the above on every push to `main` and on pull requests.

## Evaluation

```bash
uv run python scripts/evaluate_lists.py --services fake      # checks the evaluation code; free
uv run python scripts/evaluate_lists.py --services mistral   # real model: states the number of calls and asks first
```

Defaults: 4 vacancies (IT, finance, healthcare, logistics), 20 candidates each, 3 screening runs, 2 name swaps. The script uses its own database (`<name>_eval`) and writes a Markdown and a JSON report to `reports/`. Reports of fake runs are not committed: they only show that the evaluation code works (a fake that answers from the ground truth must score perfectly, and a test checks that a fake that ranks badly and invents claims is caught).
