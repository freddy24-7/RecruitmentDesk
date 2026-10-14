# Stage 8: Evaluation and hardening

Date: 2026-10-14

## What was built

- **`scripts/evaluate_lists.py`** runs four scenarios (Cloud Engineer, Financial Controller, District Nurse, Supply Chain Planner) through the app's own API: generate and submit the vacancy, generate the candidates, save the proposed script unedited, run the screening several times. It writes a Markdown and a JSON report to `reports/`. It uses its own database (`<name>_eval`), so it never touches the development or test data.
- **What the report measures, against the planted ground truth:**
  - short-list precision and long-list recall for the planted strong matches;
  - the same two figures with facts only (code's scores), model only (the fit score) and both (the setting in use);
  - unflagged hard misses (must be 0) and flagged entries;
  - evidence accuracy: the share of the model's claims about keywords and years that the CV supports;
  - consistency: the overlap (Jaccard) of the lists over repeated runs;
  - name swap: the same CV, with the name written into it, assessed under two names; the report shows whether the model's input was identical and the score difference;
  - a vacancy rubric checked in code, and cost and latency per call type from the usage records.
- **Daily spend cap** (`DAILY_SPEND_CAP_USD`, default $2.00). It is the sum of today's usage records (UTC). Once reached, no job starts and a running job stops at its next model call, with "The demo has reached its budget for today…". Everything else keeps working.
- **Clean-up on a timer.** Every `CLEANUP_INTERVAL_MINUTES` (and once at startup), workspaces idle for longer than `SESSION_IDLE_HOURS` are deleted with all their data. Failed code attempts older than a day are removed. Usage records are kept, without a workspace, so the spend cap and the cost figures stay correct.
- **"Reset demo"** in the header deletes every vacancy of the workspace after a confirmation that says so. The session and the workspace's limits stay: a reset does not give a visitor a fresh budget.
- **Request size limit** (`MAX_REQUEST_BYTES`, 256 kB): larger requests get 413.

## How the rules are kept

- **One deletion path.** The clean-up and "Reset demo" live in `app/vacancy/deletion.py`, next to "Cancel vacancy", and "Reset demo" requires the explicit confirmation flag.
- **Limits in one place.** The spend cap is checked in `app/limits` before a job starts and in the one door to the model before every call.
- **The evaluation goes through the API**, as a visitor does: one workspace per vacancy, the normal per-workspace limits, blind screening, the evidence check. It does not reach around the application to get better numbers.
- **The evaluation code is tested** (`tests/integration/test_evaluation.py`). A fake that answers from the ground truth must score perfectly, and must make exactly the number of calls the script announces before asking for confirmation. A fake that reverses the scores and claims a keyword no CV contains must be caught: model-only precision drops and evidence accuracy falls below 1, while the facts-only ranking and the hard requirements are unaffected.

## Decisions and why

- **$2.00 per day as the default cap.** A full visitor session (vacancy, 100 candidates, script, lists, questions) costs a few cents, so this allows dozens of sessions a day and bounds a bad day. It uses estimated prices, so the Mistral account still needs its own spending limit (PRD 11).
- **Ties are broken by the ranking computed by code.** The first full fake run showed a short-list overlap of 0.0 for one vacancy while the long list was identical: two candidates with the same final score swapped places between runs, because the database returned them in no fixed order. The lists now read the assessments in a fixed order, so the same input always gives the same lists. This was a real bug in the app, not only in the evaluation.
- **Reports of fake runs are not committed** (`reports/*-fake.*` is ignored). They show that the code works, not how good the model is. Reports of real runs are kept as evidence.

## What was seen in practice

- 757 backend tests (coverage 97%), 97 frontend tests and 8 browser tests pass. Lint, types and the build are clean.
- **Full fake run** (4 vacancies, 20 candidates, 3 screening runs, 2 name swaps): 252 calls, as announced. Every figure is 1.00, 0 unflagged hard misses, name swaps identical. Expected, and only a check of the code.
- **A finding from writing the "bad model" test:** with 10 candidates, a model that ranks everyone the wrong way round still produced the right short list, because only the strong matches met the hard requirements and those are applied by code. With 20 candidates more people meet them than fit on the long list, and then a bad model does change the order. The hard requirements are a strong safeguard on small pools; on larger pools the model's score matters.
- **The evaluation has not yet run against the real model.**

## Still open

- **The real evaluation run**: 252 calls, needs approval.
- **Interview-question quality** (PRD section 10) is not measured by the script: the link check and the protected-attribute check run in the app, but there is no report figure for them yet.
- **No per-IP rate limit on generation.** Per IP, only failed code attempts are limited. A visitor is bounded by the per-workspace limits and the uses of their code, and everyone by the daily cap.
- **The name swap tests blind screening, not the model's fairness on names.** Because names are removed before the model sees the CV, identical input is expected; the test proves the anonymisation, and the score difference only shows the model's own variation.
