# Stage 2: Vacancy generation

Date: 2026-10-13

## What was built

- **One door to the model** (`app/llm/`). An interface (`LlmClient`), a Mistral implementation, a fake, and `LlmService.generate`, which every model call goes through. It validates the answer against a Pydantic schema, retries once on invalid output, and writes a usage record per call.
- **Background jobs** (`app/jobs/`). A job is a database row. It runs as an asyncio task in the web process. The UI polls for its status.
- **Vacancy generation** (`app/vacancy/`). The dialog's choices go into a versioned prompt file (`prompts/vacancy_v1.md`). The model returns eight structured sections. A check in code flags obviously discriminatory wording for review.
- **Usage records.** Model, tokens in and out, latency, estimated cost and outcome, per call.
- **Per-workspace limit.** At most 10 vacancy generations per workspace, with retries counted, and one running job at a time.
- **Frontend.** The header with "Generate vacancy" and "Submitted vacancies", the generate dialog, a spinner with a status text, the "Your vacancy is ready to be viewed" button, Retry on failure, and a read-only view of the result.
- **Second migration** (`0002`): tables `vacancy`, `job` and `usage_record`.

## Checked against Mistral before building (2026-10-13)

- **SDK:** `mistralai` 3.2.0. The import path is now `from mistralai.client import Mistral`. Older examples (`from mistralai import Mistral`) no longer apply.
- **Structured output:** supported through `response_format` with a strict JSON schema. The SDK builds the schema from a Pydantic model.
- **Retries:** the SDK retries 429 and 5xx answers itself, with backoff. So `tenacity`, which I had planned to add, was not needed.
- **Model:** the model page for Mistral Small 4 shows the identifier `mistral-small-2603`, at $0.15 per million input tokens and $0.60 per million output tokens. The page does not label which price is which; this is the usual order. Mistral Small 3.2 (`mistral-small-2506`) is retired.
- **Not verified:** that the API accepts this exact model name and our schema. That needs one real call (see "Still open").

## Decisions and why

- **Our own validation, not the SDK's `parse` helper.** We call `complete` with the JSON schema and validate the answer ourselves. That keeps the retry rule and the usage record in one place, identical for the real model and the fake.
- **Limits are validators, not JSON-schema keywords.** The schema sent to the API contains only strings and lists of strings. Rules such as "at least one responsibility" are checked in code afterwards. A strict schema mode may refuse keywords like `minItems`, and I could not test that without a key.
- **Usage is written in its own transaction.** A call that cost money is recorded even if the job fails afterwards. Both attempts of a retried call are recorded.
- **The fake is recorded as model `fake` at cost zero**, so development never looks like spend.
- **A model without a known price stops the app at startup.** Otherwise spend would be invisible, and the daily cap in stage 8 depends on these figures.
- **Jobs are claimed with a conditional update.** Starting the same job twice runs it once. Retry is conditional in the same way, so a double click queues it once.
- **Starts are counted, not vacancies.** A retry costs model calls too, and deleting a vacancy later must not give the budget back.
- **Form input is treated as data.** The title and the "anything to emphasise" text sit between tags in the prompt, and the system prompt says to treat them as information, never as instructions.
- **Flagged wording is shown, not removed.** The check is a short list of terms. It flags for a person to review. It is not a test for discrimination.
- **The dialog is a Radix Dialog.** It traps focus, closes on Escape and labels itself for screen readers. The frontend list is polled with TanStack Query only while something is being generated.
- **The server owns the lists and limits.** Sectors, seniorities, work modes and field lengths come from one endpoint, so they are not written twice.
- **Tailwind was left out.** The tech list suggested it. Plain CSS has been enough so far, and it is one dependency less. It can still be added.

## What was seen in practice

- 206 backend tests pass with 98% coverage. 22 frontend tests pass. Lint, types and the build are clean.
- **Tests that break the rules on purpose pass:** a stray SDK import in another module is caught, and a route added outside the session guard is caught (the new vacancy and job routes are covered automatically).
- **Invalid output:** tried with prose, an empty answer, a missing field, a wrong type and JSON inside a code fence. Each is retried once, and fails with `llm_invalid_output` if the second answer is also unusable.
- **Interrupted jobs:** a job left "running" is marked `interrupted` at startup, the user sees why, and Retry finishes it.
- **Log test:** the steps are logged with ids and counts. The title, company, emphasis text and generated text do not appear.
- **A live run with the fake model** through the dev server: the request returned at once with status "generating", a second start was refused while the first ran, and the vacancy was a draft a moment later.
- **Surprise:** FastAPI 0.143 no longer lists included routes directly in `app.routes`. The route check now uses `iter_route_contexts`.

## Still open

- **Nothing has run against the real Mistral API yet.** Everything above was tested with the fake or with the SDK call replaced by a stub. One real call is prepared (`uv run pytest -m mistral tests/real -s`). It needs an API key and costs well under one cent. It will show whether the model name and the schema are accepted, and what a vacancy really costs.
- **Vacancy quality is unknown** until that call: whether the sections are specific, and whether the qualifications are concrete enough for the selection script in stage 5.
- **The price order (input, output) is assumed**, as noted above.
- **The vacancy view is read-only.** Editing, cancelling and submitting are stage 3.
- **Not tried in a real browser.** The dialog is tested in jsdom, including focus and Escape. Playwright comes in stage 3.
- **No daily global spend cap yet** (stage 8). Until then the bound is the per-workspace limit times the number of sessions. The app is not deployed, so there is no exposure.
- **Jobs run in the web process.** This needs exactly one process and one replica in production.
