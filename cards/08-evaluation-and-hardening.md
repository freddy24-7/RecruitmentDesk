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
  - interview questions from the last short list: sets made, questions kept, questions dropped for naming a source that was not offered, questions flagged for a protected attribute, and questions whose text still shows a reference code such as "P1";
  - a vacancy rubric checked in code, and cost and latency per call type from the usage records.
- **Daily spend cap** (`DAILY_SPEND_CAP_USD`, default $2.00). It is the sum of today's usage records (UTC). Once reached, no job starts and a running job stops at its next model call, with "The demo has reached its budget for today…". Everything else keeps working.
- **Clean-up on a timer.** Every `CLEANUP_INTERVAL_MINUTES` (and once at startup), workspaces idle for longer than `SESSION_IDLE_HOURS` are deleted with all their data. Failed code attempts older than a day are removed. Usage records are kept, without a workspace, so the spend cap and the cost figures stay correct.
- **"Reset demo"** in the header deletes every vacancy of the workspace after a confirmation that says so. The session and the workspace's limits stay: a reset does not give a visitor a fresh budget.
- **Per-IP limit on new sessions** (`MAX_SESSIONS_PER_IP_PER_HOUR`, 5). Each session is a fresh workspace with its own budget of runs, so this bounds what one address can spend. It is checked before the code is counted, so a refused request does not use up a redemption. A transaction lock per address makes simultaneous requests count one after another: a test sends 12 at once from one address and gets exactly 5 sessions, and fails when the lock is removed. Workspaces store a keyed hash of the address (migration `0008`), never the address.
- **Request size limit** (`MAX_REQUEST_BYTES`, 256 kB): larger requests get 413.

## How the rules are kept

- **One deletion path.** The clean-up and "Reset demo" live in `app/vacancy/deletion.py`, next to "Cancel vacancy", and "Reset demo" requires the explicit confirmation flag.
- **Limits in one place.** The spend cap is checked in `app/limits` before a job starts and in the one door to the model before every call.
- **The evaluation goes through the API**, as a visitor does: one workspace per vacancy, each from its own documentation address (192.0.2.x), the normal per-workspace limits, blind screening, the evidence check. It does not reach around the application to get better numbers.
- **The evaluation code is tested** (`tests/integration/test_evaluation.py`). A fake that answers from the ground truth must score perfectly, and must make exactly the number of calls the script announces before asking for confirmation. A fake that reverses the scores and claims a keyword no CV contains must be caught: model-only precision drops and evidence accuracy falls below 1, while the facts-only ranking and the hard requirements are unaffected. Interview questions that ask "How old are you?", name an unknown source and show a reference code are counted as flagged, dropped and leaking.

## Decisions and why

- **$2.00 per day as the default cap.** A full visitor session (vacancy, 100 candidates, script, lists, questions) costs a few cents, so this allows dozens of sessions a day and bounds a bad day. It uses estimated prices, so the Mistral account still needs its own spending limit (PRD 11).
- **Ties are broken by the ranking computed by code.** The first full fake run showed a short-list overlap of 0.0 for one vacancy while the long list was identical: two candidates with the same final score swapped places between runs, because the database returned them in no fixed order. The lists now read the assessments in a fixed order, so the same input always gives the same lists. This was a real bug in the app, not only in the evaluation.
- **5 sessions per address per hour.** Enough for a person who tries the demo a few times; the cost is that colleagues behind one office network share the limit. Spend per visitor is also bounded by the per-workspace limits, the 20 uses per code and the daily cap.
- **The fake follows the interview prompts.** It used to put the reference code in the question text, which the v2 prompts forbid; the evaluation counted 30 of 30 questions as leaking a code. It now puts the reference only in `source`, so a perfect fake scores 0 there.
- **Reports of fake runs are not committed** (`reports/*-fake.*` is ignored). They show that the code works, not how good the model is. Reports of real runs are kept as evidence.

## What was seen in practice

- 764 backend tests (coverage 97%), 97 frontend tests and 8 browser tests pass. Lint, types and the build are clean.
- **Full fake run** (4 vacancies, 20 candidates, 3 screening runs, 2 name swaps, interview questions): 264 calls, as announced. Every figure is 1.00, 0 unflagged hard misses, name swaps identical; 30 interview questions, none dropped, flagged or showing a code. Expected, and only a check of the code.
- **A finding from writing the "bad model" test:** with 10 candidates, a model that ranks everyone the wrong way round still produced the right short list, because only the strong matches met the hard requirements and those are applied by code. With 20 candidates more people meet them than fit on the long list, and then a bad model does change the order. The hard requirements are a strong safeguard on small pools; on larger pools the model's score matters.
- **First real run (2026-10-14) did not finish.** After 206 real calls ($0.12 from the usage records), one name-swap call timed out after 60 seconds, and because those calls are made by the evaluation itself, outside a job, the error ended the run before a report was written. Three of four scenarios had already run. The evaluation now records a failed name-swap call in the report and goes on, and a scenario that fails is listed as "not completed" while the others are still reported. Both are tested with a fake that fails on purpose.
- Along the way: 7 of 66 CV answers were invalid and retried, and one CV failed twice, so one pool had 19 candidates instead of 20.
- **Second real run (2026-10-14, complete):** report in `reports/evaluation-20261014-1346-mistral.md`. 256 calls, estimated $0.156, about 9 minutes. Models: small for vacancy, CVs, assessment and questions; medium for profile and script.
  - **Lists:** short-list precision and long-list recall 1.00 for all four vacancies; 0 unflagged hard misses; the lists were identical over three runs. Facts only and model only gave the same result. On these pools the model's ranking adds nothing measurable: there are only 2 or 3 planted strong matches and code already finds them. That says more about how easy synthetic pools are than about the model.
  - **Flagged entries are common:** 6 of 6 listed for Cloud Engineer and District Nurse. The proposed scripts had 6 or 7 hard items (Cloud Engineer: also ISO 27001 and monitoring tools as hard), so almost nobody met them all and the fallback with a visible flag applied. The rule worked as designed; a recruiter would edit the script first. The evaluation saves the proposal unedited on purpose.
  - **Evidence accuracy 0.46 to 0.73.** For Cloud Engineer more than half of the model's claims about keywords and years were not supported by the CV and were removed or corrected. Lower than in stage 6 (0.63 to 0.75), with longer scripts.
  - **Script grouping is still imperfect:** "Dutch | EU financial regulations | tax laws" as alternatives, and "Dutch" both hard and soft in one script.
  - **Name swap:** identical model input in 8 of 8 cases, score difference 0.
  - **Interview questions:** 70 questions, none dropped, none flagged, none with a reference code in the text.
  - **CVs:** 9 of 84 answers were invalid and retried; three pools ended with 18, 18 and 19 of 20 candidates (two candidate jobs failed on a timeout, one on invalid output). The evaluation does not retry a failed job, as a user could.
  - **Vacancy rubric:** "seniority mentioned" is NO for both medior vacancies. They state the level only through years of experience, without a level word; the check is stricter than a reader would be.

## Still open

- **Harder pools.** Every figure for the lists is 1.00 on synthetic pools; a pool with near-misses (strong candidates who lack one hard item, misleading CVs) would test the model's ranking.
- **Evidence accuracy is low for long scripts.** The check removes the unsupported claims, but a prompt or model change could reduce them; not tried.
- **Interview questions are measured by their links and flags only.** Whether a question is good, and whether a reference fits the question (the Grafana example in stage 7), is not measured. The name swap is not run for follow-up questions; they are written from the same anonymised CV as the assessment.
- **"Reference codes in the text" counts the AWS service S3 too**, so an IT vacancy can show a code that is not a leak.
- **The per-IP limit trusts the address the server sees.** Behind a proxy (as on Railway) that has to be the client's address, not the proxy's; this is checked at deployment (stage 9).
- **The name swap tests blind screening, not the model's fairness on names.** Because names are removed before the model sees the CV, identical input is expected; the test proves the anonymisation, and the score difference only shows the model's own variation.
