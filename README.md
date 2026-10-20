# RecruitDesk

A demo web app that shows how a large language model (Mistral) can support the first stages of recruitment: write a vacancy, create fictional candidates, turn the vacancy into screening criteria, propose a long list and a short list with a reason per candidate, and prepare interview questions.

**This is a demo, not a product.** All candidates are fictional, generated for the demo. Nothing here should be used to make real hiring decisions.

The specification is in [docs/PRD.md](docs/PRD.md). A note per build stage (what was decided, what was seen, what is still open) is in [cards/](cards/). The app is ready to deploy but has not been deployed: see [How to deploy](#how-to-deploy).

## What it does

1. **Generate a vacancy.** Choose a sector, title, seniority and work mode. A background job writes the vacancy in structured sections. Wording about age, gender, nationality and similar attributes is forbidden in the prompt, and a check in code flags it for review.
2. **Review and submit.** Edit the sections, reset to what was generated, or cancel (after a confirmation that says what will be deleted).
3. **Generate candidates.** 1 to 100 fictional candidates. Code decides who each candidate is (skills, years of experience, how well they match), builds their dated job history and keeps that as ground truth. The model only writes the CV text.
4. **Selection script.** The model proposes screening criteria from the vacancy: keywords with alternatives, minimum years, hard or soft, and the sentence in the vacancy each one comes from. Code checks that the sentence is really there. The recruiter edits and submits.
5. **Long list and short list.** Code finds the keywords in each anonymised CV, computes years from the dated jobs and applies the hard and soft requirements. The model assesses the strongest candidates and writes a reason. Code checks the model's claims against the CV and removes what is not supported. Names and contact details are added back only for display.
6. **Interview questions.** Core questions for every short-listed candidate, so interviews can be compared, and follow-ups per candidate. Each question names the criterion, strength or concern it is based on, and code checks that link.

Every list carries the notice "Suggestions to support a recruiter. A person decides."

## How it is built

- **Backend:** Python 3.12, FastAPI, async throughout. PostgreSQL with SQLAlchemy 2 and Alembic. Pydantic v2 for every schema.
- **Model:** the official Mistral Python SDK, used directly. `mistral-small-2603` for most steps; `mistral-medium-2604` for the two calls made once per vacancy, where the stronger model read the vacancy better (the vacancy profile and the script proposal).
- **Frontend:** React with TypeScript (Vite), TanStack Query for polling job status, Radix for accessible dialogs.
- **Jobs:** stored in the database and run in the web process. Progress is saved as it goes; a job cut off by a restart is marked "interrupted" and can be retried. The UI polls and never blocks.
- **Deployment:** one Docker image (frontend served by the backend), aimed at Railway.

### Design choices and trade-offs

- **The SDK directly, not LangChain or LangGraph.** The pipeline is a fixed sequence of steps with code in between, not an agent that chooses its own path. Plain functions and one thin interface (`app/llm/`) make every prompt, retry and cost visible, and make the model easy to replace with a fake in tests. The price: retries, usage records and structured-output handling are written by hand instead of coming with a framework.
- **Structured output only.** Every answer is JSON checked against a Pydantic schema. An invalid answer is retried once, then the step fails with a clear error. Nothing is read out of free text.
- **Code first, the model second.** Facts that code can establish (is the keyword in the CV, how many years, is a hard requirement met, how long are the lists) are never left to the model. The model adds judgement and the written reason, and its claims are checked.
- **Jobs in the web process, not a queue.** Enough for a demo and one less service to run. The cost: exactly one replica, and a restart interrupts running jobs (which can then be retried).
- **The model per step,** chosen after side-by-side runs: the medium model gave the same lists as the small one at ten times the price for assessment, but read the vacancy noticeably better for the two once-per-vacancy calls.

## Safeguards

Each rule lives in one place in the code, and a test breaks it on purpose to prove the check works.

| Rule | How | Proved by |
| --- | --- | --- |
| One door to the model | Only `app/llm/mistral.py` imports the SDK | A source scan, also run on a tree with a stray import (`tests/unit/test_llm_boundary.py`) |
| Blind screening | Assessment gets an anonymised CV: no name, email or phone, also when they appear inside the CV text | `tests/integration/test_screening.py` |
| Facts computed by code | Years from dated jobs; a keyword counts only if it is in the CV; unsupported claims removed and flagged | `tests/integration/test_screening.py`, `tests/unit/test_screening_logic.py` |
| Hard and soft requirements in one function | A hard requirement must be met, unless too few candidates meet it; then the candidate is listed with a visible flag | `tests/unit/test_requirements.py` |
| List sizes in one function | Long `min(10, max(1, round(0.30 × N)))`, short `min(4, max(1, round(0.10 × N)))`, round half up | Edge cases N = 1 to 100 |
| One deletion path | "Cancel vacancy", "Reset demo" and the clean-up of idle workspaces all delete through `app/vacancy/deletion.py`; the first two need an explicit confirmation flag | A source scan for a second path (`tests/unit/test_single_deletion_path.py`) |
| Nothing reachable without a session | Every API route except the code entry and the health check needs a session | Every route requested without one (`tests/integration/test_route_protection.py`) |
| Access codes never stored or logged | Keyed hashes only; codes counted atomically | 25 simultaneous redemptions of a code with one use left give one success |
| No personal data in logs | Ids, counts and error kinds only | Tests search the logs for CV text and codes |
| Spend and abuse limits | Daily spend cap, per-workspace limits, 5 new sessions per IP address per hour, 100 candidates per vacancy, request size | `tests/integration/test_hardening.py`, `tests/integration/test_access_gate.py` |

## Results

What was measured, and how. Everything in this section ran against the real Mistral API on 2026-10-13 and 14: about 780 calls, an estimated 54 cents in total, taken from the usage record every call writes. All automated tests use a fake model instead.

**The evaluation** ([report](reports/evaluation-20261014-1346-mistral.md)): four vacancies (IT, finance, healthcare, logistics), 18 to 20 candidates each with a planted match category, three screening runs each, the script used as the model proposed it. 256 calls, $0.156.

| Measure | Result |
| --- | --- |
| Short-list precision (share of the short list that are planted strong matches) | 1.00 for all four |
| Long-list recall (share of strong matches on the long list) | 1.00 for all four |
| Listed with a missed hard requirement and no flag | 0 |
| Same lists over three runs on the same input | Yes, for all four |
| Model's claims about keywords and years that the CV supports | 46%, 69%, 71%, 73%. The rest was removed before display |
| Name swap: same CV, two names, identical model input | 8 of 8; score difference 0 |
| Interview questions dropped for a bad link, or flagged | 0 of 70, 0 of 70 |

What these numbers do and do not show:

- **The lists are perfect because the pools are easy.** Ranking by code alone, or by the model alone, also scored 1.00: with 2 or 3 strong matches per pool, the facts computed by code already find them. A harder pool (near-misses, misleading CVs) is needed to show what the model's judgement adds.
- **The model often claims more than the CV supports.** Up to 54% of its claims about keywords and years did not hold for one vacancy. The evidence check is what keeps them off the screen.
- **The proposed scripts are too strict.** Six or seven hard items made almost everyone miss one, so most listed candidates carried a flag. A recruiter would trim the script; the evaluation does not, on purpose.
- **Generation is not perfectly reliable.** 9 of 84 CV answers were invalid and retried; three pools ended one or two candidates short after timeouts. A first evaluation attempt stopped on a timeout, which led to the evaluation recording failures instead of stopping.
- **The name swap tests the anonymisation.** Names are removed before the model sees the CV, so identical input is expected. It does not show how the model would treat names it could see.

**Cost per step**, from the average measured cost per call in the evaluation (estimated from token counts and list prices):

| Step | Model | Per call | Per unit |
| --- | --- | --- | --- |
| Vacancy | small | $0.0005 | one vacancy, plus $0.0056 for the vacancy profile (medium) |
| CV | small | $0.0003 | 100 candidates: about $0.03 |
| Script proposal | medium | $0.0053 | once per vacancy |
| Assessment | small | $0.0005 | one screening run of up to 20 assessed candidates: about $0.01 |
| Interview questions | small | $0.0004 | one run of up to 5 sets: about $0.002 |

A complete session (one vacancy, 100 candidates, script, lists, questions) therefore costs about 5 to 6 cents. Average latency per call was 3 to 4 seconds (vacancy text about 9); 20 CVs were written in 19.5 seconds with 4 at a time.

More detail, including what went wrong and was fixed along the way, is in the stage notes: [04](cards/04-candidates.md), [05](cards/05-selection-script.md), [06](cards/06-long-list-and-short-list.md), [07](cards/07-interview-questions.md), [08](cards/08-evaluation-and-hardening.md).

## Honest limits

- **Synthetic candidates are easier than real ones.** A generated CV never names a skill its owner lacks, and the CVs share patterns. The figures above are an upper bound.
- **Results depend on the model version.** The versions are pinned (`mistral-small-2603`, `mistral-medium-2604`); a newer model can behave differently and must be evaluated again.
- **AI in recruitment is a high-risk use.** The EU AI Act treats it as high-risk. This demo shows safeguards (blind screening, facts checked by code, a person decides, no protected attributes), but it is not a compliant production system: there is no bias audit on real data, no human-oversight process, no record keeping for decisions, and no route for candidates to contest a result.
- **The protected-attribute checks are short lists of terms.** Discriminatory wording that avoids those terms passes them.
- **The access code is a light protection.** It limits casual use and cost, not determined abuse. A public code can be used up by anyone, by design.
- **Deployment is prepared, not done.** The image, the production settings and the deployment checks were tested locally; nothing has run on Railway.

## Status

Built in ten stages (PRD section 13), each ending with tests and a note in [cards/](cards/):

0. Skeleton: backend, database, migrations, frontend, tests, CI.
1. Access gate: access codes, sessions, private workspaces, protection against guessing.
2. Vacancy generation: the one door to the model, structured output, background jobs, usage records.
3. Review, edit, cancel and submit.
4. Candidates: blueprints sampled by code as ground truth, CVs written by the model.
5. Selection script: criteria proposed from the vacancy, quotes checked by code.
6. Long list and short list: blind screening, scores computed by code, assessment by the model, the evidence check.
7. Interview questions, with checked links to their source.
8. Evaluation against the ground truth, and hardening: daily spend cap, clean-up of idle workspaces, "Reset demo", per-IP session limit, request size limit.
9. Deployment and write-up: the Docker image, production mode, deployment checks and this README. **The deployment itself has not been done.**

777 backend tests (97% coverage), 97 frontend tests and 8 browser tests pass, with lint and strict type checks, in CI on every push.

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

Before the first run, copy `.env.example` to `.env` and fill in the two secrets (`ACCESS_CODE_PEPPER` and `SESSION_SECRET`). The file explains how to generate them and documents every other setting. The app does not start without them. Never commit `.env`. Then create an access code (see [Access codes](#access-codes)).

The backend also serves the built frontend from `web/dist` when that folder exists. After `npm --prefix web run build`, the whole app is on http://localhost:8000 without the Vite dev server.

## The model

`LLM_PROVIDER` in `.env` chooses the model:

- `fake` answers without the network and without cost. Use it for development. Its text is labelled "[Fake model output]".
- `mistral` calls the real Mistral API and costs money. It needs `MISTRAL_API_KEY`.

The model version for each step is pinned in the `MISTRAL_MODEL_*` settings. A model also needs a price in `app/llm/pricing.py`, or the app refuses to start. Prompts are versioned files in `prompts/`; the version is stored with every result.

Jobs run inside the web process, so run exactly one process (no `--workers`, one replica).

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

## How to deploy

The app is one Docker image ([Dockerfile](Dockerfile)): the built frontend served by the FastAPI backend, on one origin. On start it runs the migrations, then the app ([deploy/start.sh](deploy/start.sh)). Jobs run inside the web process, so it runs as **one replica**. The steps below are for Railway; any host that runs a Docker image next to PostgreSQL works the same way.

With `APP_ENV=production` the app refuses to start unless a daily spend cap, secure cookies and the client IP header are set (and an API key, with the real model). That keeps a public deployment from running without its protections.

### Try the production image locally first

```bash
docker build -t recruitdesk .
docker run --rm -p 8080:8000 --env-file <a production-like env file> recruitdesk
uv run python scripts/check_deployment.py http://localhost:8080
```

Use a separate env file with new throwaway secrets and a database URL reachable from the container (for the local PostgreSQL: `postgresql://recruitdesk:recruitdesk@host.docker.internal:5433/<a scratch database>`). Locally `--spoofing` fails, as it should: nothing in front of the app overwrites the address header.

### Cost

Railway Hobby: $5 a month, which includes $5 of usage. The app and its database need about 0.5 GB of memory together and little CPU, so expect roughly $5 to $10 a month in total ([prices](https://docs.railway.com/reference/pricing/plans), checked 2026-10-14). Mistral is billed separately and is limited by the daily spend cap: $1.00 a day allows about 15 to 20 full sessions. **Delete the project when the demo is no longer needed** (see the end of this section).

### Set up (once, in the Railway dashboard)

1. On the Mistral console, set a monthly spending limit (for example $10) and create a **separate API key for production**, so it can be revoked on its own.
2. New project, then **Deploy from GitHub repo** and choose this repository. Railway finds the `Dockerfile` itself. (There is no `railway.json`: Railway's Config as Code is deprecated, so the settings below are made in the dashboard.)
3. In the project, **add PostgreSQL**.
4. In the app service, under **Settings**:
   - Healthcheck path: `/health`.
   - Replicas: 1. Serverless (sleeping): off, so a visitor never meets a cold start.
   - Restart policy: on failure.
   - Source: deploy on push to `main`, with **Wait for CI** on, so only a commit that passed CI is deployed.
   - Networking: generate a domain.
5. In the app service, under **Variables** (typed in the dashboard as one line without quotes, never in the repository or a chat):

   | Variable | Value |
   | --- | --- |
   | `APP_ENV` | `production` |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (a reference to the database) |
   | `ACCESS_CODE_PEPPER` | a new secret: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Keep it in a password manager |
   | `SESSION_SECRET` | another new secret, made the same way |
   | `LLM_PROVIDER` | `mistral` |
   | `MISTRAL_API_KEY` | the production key |
   | `DAILY_SPEND_CAP_USD` | `1.00` |
   | `CLIENT_IP_HEADER` | `x-real-ip` (where Railway's edge passes the visitor's address) |
   | `COOKIE_SECURE` | `true` |
   | `CONTACT_URL` | the link shown when a code is used up, for example a LinkedIn profile |

   The model versions and the limits have defaults in `app/config.py`; `.env.example` lists them all.

### Deploy

Push to `main`. CI runs (including building the image), and Railway then builds and starts the new version. A failed health check keeps the old version running. The log should show the migrations, then "Application startup complete".

### Check the deployment

```bash
uv run python scripts/check_deployment.py https://<app>.up.railway.app             # health, frontend, every API route 401 without a session
uv run python scripts/check_deployment.py https://<app>.up.railway.app --spoofing  # a made-up IP header must not get around the lockout
```

`--spoofing` sends 11 malformed codes, each with a different made-up address in the headers. It must report a lockout: that shows the app counts the address the host saw, not one a visitor sends. It locks your own address out of the code screen for 15 minutes; then open the app from another network (a phone without wifi) and check that it is **not** locked out. That shows visitors are told apart, not all counted as one. If either check fails, do not share the link: the per-IP limits do not hold.

Optional: an uptime monitor (for example UptimeRobot) on `https://<app>/health`. That route does no database or model work, so monitoring costs nothing.

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
docker build -t recruitdesk .                   # the production image

uv run pytest -m mistral tests/real -s             # six real Mistral calls (under one cent); needs MISTRAL_API_KEY

npm --prefix web run build                         # the browser tests use the built frontend
uv run playwright install chromium                 # once
uv run pytest -m e2e tests/e2e                     # browser tests: real frontend and backend, fake model

npm --prefix web run lint
npm --prefix web run build      # type check and production build
npm --prefix web test
```

CI (GitHub Actions) runs all of these on every push to `main` and on pull requests, except the real-API tests.

## Evaluation

```bash
uv run python scripts/evaluate_lists.py --services fake      # checks the evaluation code; free
uv run python scripts/evaluate_lists.py --services mistral   # real model: states the number of calls and asks first
```

Defaults: 4 vacancies (IT, finance, healthcare, logistics), 20 candidates each, 3 screening runs, 2 name swaps, and interview questions from the last short list: about 264 calls and 16 cents with the real model. The script runs each vacancy through the app's own API, as a visitor would, in its own database (`<name>_eval`), and writes a Markdown and a JSON report to `reports/`. A call or a vacancy that fails is recorded in the report; the run goes on.

Reports of fake runs are not committed: they only show that the evaluation code works. A fake that answers from the ground truth must score perfectly, and tests check that a fake that ranks badly, invents claims or writes bad questions is caught.

## Project layout

```
app/
  access/      access codes, sessions, workspaces
  llm/         the one door to the model: interface, Mistral client, fake, usage records, prices
  vacancy/     generation, review, the one deletion module
  candidates/  blueprints (ground truth), job timelines, CV generation
  script/      selection script proposal and the hard/soft requirement logic
  screening/   blind CVs, facts computed by code, assessment, evidence check, list sizes
  interview/   interview questions, link check, protected-attribute check
  jobs/        background jobs in the database
  limits/      spend cap, per-workspace and per-IP limits, failed-attempt limits
  evaluation/  the evaluation against the ground truth
  web/         API routes
prompts/       versioned prompt files
web/           React frontend
scripts/       access codes, evaluation, deployment checks, screenshots
tests/         unit, integration, browser and real-API tests
cards/         a note per build stage
reports/       evaluation reports of real runs
deploy/        the container's start script
docs/PRD.md    the specification
```
