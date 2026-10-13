# Stage 4: Candidates

Date: 2026-10-13

## What was built

- **Generate candidates** for a submitted vacancy: a dialog asks for a number from 1 to 100, a background job creates them, and progress shows as "x of N candidates created".
- **Vacancy profile.** One model call per vacancy version extracts the skills (with the years asked for) and a few adjacent and unrelated roles.
- **Blueprint sampler** (`app/candidates/blueprints.py`). Code decides who each candidate is: name, seniority, a dated job timeline, the skills used in each job, and a match category. Seeded, so a pool can be reproduced.
- **CV writing.** The model writes the prose for one blueprint at a time, four at a time. Code adds the dates, the skills per job, languages and contact details.
- **Candidate page** per vacancy: searchable, sortable, with a CV detail view and a "synthetic data" label.
- **Regenerating** replaces the existing candidates, after the dialog has said so.
- **Out of date.** Editing the vacancy marks its candidates as out of date, on the list, on the vacancy and on the candidate page.
- **Fourth migration** (`0004`): the `candidate` table, `job.params`, `vacancy.profile`.

## Decisions and why

- **Code builds the job timeline; the model writes only the prose.** The PRD had the model write the dated employment history. Then the planted years per skill would depend on the model getting dates right, and the evaluation in stage 8 would measure noise. Now the years computed from a CV are exactly the planted years, with the same function on both sides (`app/candidates/timeline.py`).
- **One extra model call for the vacancy profile.** The sampler needs to know the vacancy's skills, and what an adjacent or unrelated job looks like. The result is stored with the vacancy version, so the same text is not analysed twice.
- **The model never learns who a CV is for.** The CV prompt gets no name and no contact details, and not the match category. The CV itself holds no name either: contact details live in separate columns. This is the first half of blind screening.
- **Three checks protect the ground truth.** An answer is treated as invalid output (retried once) if it names a vacancy skill the candidate does not have, names a skill in the highlights of a job where it was not used, or contains personal details such as a birth date or marital status.
- **The match category is never served.** The API returns no blueprint. Showing it would give the demo's answer away, and it must not reach the scoring step in stage 6.
- **Always at least one strong match**, also for tiny pools. Without one, a short list could not be judged.
- **Each run has its own seed** (base seed plus the run number, stored with the job), so regenerating gives different people, and any pool can still be reproduced.
- **One failed CV does not fail the others.** The job ends as failed with "x of N created", keeps what it made, and Retry writes only the missing CVs. If the model is unreachable or rate-limited, the job stops early: no hopeless calls.
- **Limits.** 100 candidates per run (checked on the server), 300 per workspace over all runs, one job at a time, and at most three tries per job.
- **Old candidates are replaced only after the profile call succeeded**, so a failed start does not leave the vacancy empty.
- **Phone numbers use `+44 7700 900xxx`**, the range Ofcom reserves for drama. Emails use `example.com`.
- **Searching and sorting happen in the browser.** With at most 100 rows that is simpler and instant.
- **New dependency:** `faker`, for seeded fictional names (Dutch and British).

## What was seen in practice

- 425 backend tests pass with 98% coverage, 53 frontend tests and 5 browser tests. Lint, types and the build are clean.
- **Sampler:** the same seed gives the same pool; 100 candidates give exactly 15, 35, 30 and 20 per category; every pool size from 1 to 100 adds up and has a strong match. Strong matches have every required skill for at least the years asked; partial matches miss at least one; weak matches have none.
- **Blind by construction:** over a pool of 20, no CV text contains its candidate's name, email or phone number, and no request to the model does either.
- **Concurrency:** with 30 candidates the fake saw more than one call at a time, and never more than four.
- **Failure handling:** a pool of 6 with one CV that failed twice ended as "5 of 6", and Retry made exactly one more call. With a rate-limited model and 50 candidates, at most four calls were made before the job stopped.
- **The first CI run of the browser tests in stage 3 had failed** on a missing test database; that was fixed before this stage started.
- **Bug found by a test:** setting a JSON column to `None` stored JSON `null`, not SQL `NULL`, so "candidates without a CV" were not found. The column now stores `None` as `NULL`.
- The candidate list and a CV were checked by eye in a real browser, with the fake model.

- **First contact with the real Mistral API (2026-10-13), with a key on the Free plan:**
  - The key is accepted, and the model list contains `mistral-small-2603`. The pinned model name is therefore confirmed. `mistral-medium-2604` is listed too, a candidate for the assessment step in stage 6.
  - Every chat call is refused with HTTP 429. The response header `x-ratelimit-limit-req-minute` is `0`: the Free plan allows no chat requests at all. So the schema, the answer quality and the cost are still untested.
  - Our error handling turned this into "The model is busy right now. Please try again in a moment", after the SDK had retried for a minute. That message is wrong for a limit of zero, where waiting does not help.

## Still open

- **Nothing has run against the real Mistral API.** This matters more now. The fake always obeys the three ground-truth rules. A real model will sometimes break them, and how often is unknown. If it is often, many CVs will need a retry or fail, and the prompt needs work.
- **A real-API check is prepared**: `uv run pytest -m mistral tests/real -s` now also makes one profile call and four CV calls, and prints the problems found and the cost. Expected cost: under one cent.
- **Cost of 100 candidates is an estimate only**: about 100 calls of roughly 600 tokens in and 500 out, so around 4 cents at the listed prices. To be measured.
- **Rate limits.** Four calls at a time is a guess. On a low tier, 100 CVs may be slow.
- **The pool is easier than real life**, by design of the checks above: a candidate's CV never mentions a skill they lack. The README must say so (PRD section 14).
- **Skill names are matched as whole words.** "Java" does not match "JavaScript", but a model that writes "Azure" where the blueprint says "Microsoft Azure" passes the check. That is harmless for ground truth and matters for scoring in stage 6.
- **Selection script results and lists** will also need the out-of-date mark when candidates are regenerated; they do not exist yet.
