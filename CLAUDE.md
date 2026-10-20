# CLAUDE.md

Guidance for Claude Code when working on **RecruitDesk**. Read `docs/PRD.md` first. The PRD is the source of truth for scope, flows and stages. If this file and the PRD disagree, stop and ask.

## What this project is

A demo web app that shows how an LLM (Mistral) can streamline early recruitment: generate a vacancy from a few choices, review and submit it, generate fictional candidates, turn the vacancy into a selection script (screening criteria), and propose a long list and short list with a written reason for each candidate.

It is a demo, not a product. **All candidates are fictional.** There is no real personal data, ever. Nothing here is meant to support real hiring decisions.

## How we work

- Work **one stage at a time**, in the order in the PRD (section 13). Each stage ends with working software, passing tests and a short note in `cards/` (what was decided and why, what was seen in practice, what is still open).
- Before starting a stage, state the plan in a few lines. Wait for confirmation if it changes scope, adds a dependency, or spends real money on the Mistral API.
- Small, reviewable changes. One commit per logical step with a clear message.
- When something is ambiguous, ask. Do not guess at requirements. The PRD lists open decisions in section 17: do not decide those silently.

## Architecture rules (do not break these)

1. **One door to the model.** All Mistral calls go through the interface in `app/llm/`. No other module imports the Mistral SDK. A test parses the source files and fails on a stray import, and is also run against a tree that breaks the rule on purpose.
2. **Structured output only.** The model returns JSON that is validated against a Pydantic schema. On invalid output, retry once, then fail with a clear error kind. Never parse free text with regular expressions to extract decisions.
3. **Blind screening.** The scoring and assessment steps receive an anonymised CV: no name, email, phone or other personal details. Contact details are joined back only when a list is displayed. A test feeds a CV with identifiable details and checks that none reach the model input.
4. **Facts are computed by code, not claimed by the model.** Years of experience are computed from the dated employment history. Keywords counted as "found" must appear in the CV text. The model's claims are checked, and unsupported ones are removed from the rationale and flagged.
5. **Hard and soft requirements are applied in one function.** A hard requirement must be met for a candidate to be listed, unless too few candidates meet it, in which case the candidate is listed with a visible flag. A soft requirement only adds to the score.
6. **List sizes come from one function.** Long list = `min(10, max(1, round(0.30 × N)))`, short list = `min(4, max(1, round(0.10 × N)))`. `round` is round half up with integer arithmetic, not Python's built-in `round`. The short list is always a subset of the long list. Test the edges: N = 1, 2, 5, 10, 15, 20, 25, 100.
7. **Candidates are capped at 100 on the server**, not only in the form. Validate every input on the server.
8. **One deletion path for "cancel vacancy".** It deletes the draft and all related data, and requires an explicit confirmation flag from the caller. The UI shows a confirmation dialog stating what will be deleted. A test checks that no data remains.
9. **Stale data is marked, never silently reused.** If a vacancy changes after candidates, a script or lists exist, those items are flagged as out of date. Regenerating is a deliberate action.
10. **Background jobs are idempotent.** A job that is interrupted by a restart is marked `interrupted` and can be retried. Progress is stored in the database. The UI polls job status and never blocks.
11. **Spend and abuse limits are enforced in one place.** Per-workspace and per-IP rate limits, the daily global spend cap, and the candidate cap all live in one module and are tested.
12. **No CV text, vacancy text or personal data in logs or metric labels.** Log ids, counts, step names and error kinds. A test searches the logs for CV content.
13. **Discriminatory content is not generated.** The vacancy prompt forbids requirements about age, gender, nationality, and similar attributes, and a code check flags obvious terms for review. Generated CVs contain no birth date, photo, gender, marital status or nationality.
14. **Nothing is reachable without a valid session from the access gate (PRD F0).** Every API route except the code-entry endpoint and the health check requires a session cookie. A test requests every route without a session and expects 401.
15. **Access codes are never written anywhere in the repository.** Not in code, tests, docs, fixtures, CI configuration, logs, commit messages or chat. Tests use obviously fake codes. Only `scripts/manage_codes.py create` prints real codes, once, to the terminal. Codes are stored only as HMAC-SHA256 hashes with a pepper from the environment. The submitted code is never logged.
16. **Redemptions are counted atomically.** One redemption is one new session started with a code. Use a single conditional database update (`uses < max_uses`), so concurrent requests cannot exceed the limit. Test it with parallel requests: 25 simultaneous redemptions of a code with one use left give exactly one success.

## Fake data rules

- Candidate blueprints are sampled **by code** (name, years of experience, subset of vacancy skills, seniority, match category with a fixed distribution). The model only writes a CV for a given blueprint. Keep the blueprint with the candidate as ground truth.
- Emails use a reserved domain (`example.com`). Phone numbers use a clearly fictional range. The UI labels the data as synthetic.
- Use a fixed random seed for blueprint sampling, so evaluation runs are reproducible.

## Tech and conventions

- Python 3.12, FastAPI, async throughout. PostgreSQL with SQLAlchemy 2 (async) and Alembic. Pydantic v2 for schemas and settings.
- Official Mistral Python SDK, used directly (no LangChain, on purpose). Keep it behind our own interface so it can be faked and swapped.
- Frontend: React with TypeScript (Vite).
- `uv` for Python dependencies. Pin versions. Do not add a dependency without saying why.
- Type hints everywhere. `mypy --strict` and `ruff` must pass. For the frontend: TypeScript strict mode and ESLint.
- Prompts are versioned files in `prompts/`, not inline strings. The file name is the version, and it is stored with each generated result.
- **Pin exact Mistral model versions in configuration.** Do not use `-latest` aliases for evaluation runs. Use low temperature for assessments.
- Small modules with one job each. Suggested layout: `app/access`, `app/llm`, `app/vacancy`, `app/candidates`, `app/script`, `app/screening`, `app/interview`, `app/jobs`, `app/limits`, `app/web`, plus `prompts/`, `tests/`, `scripts/`, `cards/`, `deploy/`, `web/` (frontend).
- Code, comments and docs in English.

## UI requirements to keep in mind

- "Generate vacancy" and "Submitted vacancies" are always visible.
- A spinner with a status message while a job runs. The dialog can be closed without losing the job. Errors show a message and a Retry button.
- Destructive actions have a confirmation dialog that states what will be lost.
- Actions whose prerequisites are missing are visible but disabled, with the reason shown.
- Empty state for submitted vacancies: "No vacancies have yet been submitted".
- Dialogs trap focus and close with Escape. Controls are labelled. The spinner has a text alternative.
- A visible notice on the lists: suggestions to support a recruiter, a person decides.

## Testing

- `pytest` for unit and integration tests, Playwright for a few end-to-end browser tests (generate, review, submit, candidates, script, lists).
- **Mistral is replaced by a fake behind the same interface** in all tests, so the pipeline runs in seconds without the network. Real-API tests are marked `mistral` and run only on request.
- Tests break the system on purpose to prove the guarantees: a stray SDK import, an identifiable CV reaching the model, a claimed keyword that is not in the CV, a hard-requirement failure without a flag, a second deletion path.
- CI (GitHub Actions) runs lint, types and tests, and fails below the coverage gate (start at 70%).
- **Evaluation is a script, not a test:** `scripts/evaluate_lists.py` writes a report using the known blueprints: precision and recall of the lists against the planted strong matches, evidence accuracy, consistency across runs, and the name-swap fairness test. A fake that answers from the ground truth checks the evaluation code itself. Never edit the ground truth to improve a score.

## Cost and safety rules for the Mistral API

- **Do not run large generation against the real API without confirmation.** During development use small numbers (for example 5 candidates). Ask before any run of 50 or more candidates or any evaluation over the full set, and state the expected number of calls first.
- Record usage per call (model, tokens in and out, latency, estimated cost). The cost figures in the README come from these records.
- Check current rate limits before batching. Use limited concurrency and backoff on throttling.
- Verify current model names, structured-output support and prices before relying on them. Do not assume.
- **Never put API keys, database URLs or tokens in the repository, in logs or in chat.** `.env` is git-ignored and `.env.example` documents the variables.

## Deployment rules

- Public deployment needs the protections in PRD section 11: access control, private expiring workspaces, rate limits, the daily spend cap, and a spending alert on the Mistral account. Do not deploy publicly before they exist.
- Health endpoint, migrations on start, one command to deploy, and a short runbook in the README.
- **Never create or change hosting resources (for example on Railway) without explicit confirmation** in the current conversation. Show what will be created and the expected cost first. Remind the user to remove resources when they are no longer needed.

## Honesty rules

- Report only numbers that were measured, with how they were measured. Include unflattering results.
- The README states plainly what ran against the real Mistral API and what was tested with fakes only.
- State the limits: synthetic candidates are easier than real ones, results depend on the model version, and AI in recruitment is a high-risk area, so this demo shows safeguards but is not a compliant production system.
- Do not describe planned work as done, and do not claim real users or real data.

## Definition of done (per stage)

- Code works and is covered by tests that pass locally and in CI.
- `ruff`, `mypy --strict`, the frontend checks and the test suite are green.
- Relevant evaluation was run, and the result is recorded.
- A concept note is added to `cards/`.
- README and PRD status are updated if scope or decisions changed.
- No secrets, no real data, no stray billable resources.

## Commands (create these in stage 1 and keep the list current)

```bash
uv sync                                       # install Python dependencies
docker compose up -d --wait                   # local PostgreSQL on localhost:5433
uv run alembic upgrade head                   # migrations
uv run uvicorn app.main:app --reload          # backend on http://localhost:8000
npm --prefix web install && npm --prefix web run dev   # frontend dev server on http://localhost:5173
uv run pytest tests/unit tests/integration    # fast tests, no network. They create and use their own database (<name>_test) with fake secrets
uv run pytest tests/unit tests/integration --cov --cov-fail-under=70   # as CI runs them, with the coverage gate
uv run pytest -m mistral tests/real -s        # real Mistral API, costs money: only on request, never in CI
npm --prefix web run build && uv run pytest -m e2e tests/e2e   # browser tests (first time: uv run playwright install chromium)
uv run ruff check . && uv run ruff format --check . && uv run mypy .
uv run python scripts/check_tracked_files.py  # fails if Git tracks a codes file or a .env file
uv run python scripts/manage_codes.py status  # uses per code label (never prints the codes)
# manage_codes.py create|extend|disable also exist. Run create only on the developer's machine, never in CI.
uv run alembic revision --autogenerate -m "..."   # new migration after a model change; review it by hand
npm --prefix web run lint && npm --prefix web run build && npm --prefix web test   # frontend: ESLint, types and build, Vitest
uv run python scripts/evaluate_lists.py --services fake   # evaluation with the fake model: checks the evaluation code. Own database (<name>_eval)
uv run python scripts/evaluate_lists.py --services mistral  # real model, costs money: states the calls and asks first. Only on request
docker build -t recruitdesk .                 # the production image (also built in CI)
uv run python scripts/check_deployment.py <url> [--spoofing]   # checks a deployment from outside: health, 401s, IP header
uv run python scripts/take_screenshots.py <url>   # README screenshots; asks for a code (not shown), costs ~3 cents on the real model
```

## Working with the author

The author is a developer moving into AI engineering and uses this project to learn: working directly with a model provider SDK, structured output, evaluation with ground truth, and responsible AI in a sensitive domain. Explain choices briefly, name the trade-offs (especially compared with the earlier IntakeFlow project, which used LangChain, LangGraph and Azure), and prefer clear code over clever code.
