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

- **First real model calls (2026-10-13, Pro plan, `mistral-small-2603`), six in total, measured by `uv run pytest -m mistral tests/real -s`:**
  - **The API accepts our strict JSON schemas** for all three call types (vacancy, vacancy profile, CV). This was the main unknown since stage 2.
  - **Vacancy:** 465 tokens in, 845 out, 5.7 seconds, estimated $0.00058, valid on the first answer, no flagged wording.
  - **CVs:** four calls, one per match category, about 500 tokens in and 300 to 440 out, estimated $0.0003 each. **Three of the four first answers were usable.** The fourth (the weak match) named a skill in a job where it was not used. In the app that answer is retried once.
  - **Vacancy profile:** the call worked, but its input was the thin text of the fake vacancy. It returned only two required skills, one of them vague ("cloud engineering"), and it attached "3 years" to Microsoft Azure although the text asks for three years in a comparable role. Not a fair test of the prompt, but a warning: the profile needs checking on a real vacancy.
  - **Total estimated cost of the six calls: $0.0015.**
  - A sample of four CVs says little about the failure rate. A run of 20 or more through the app is needed for a figure.

## The first real run through the app, and what it changed (2026-10-13)

One real vacancy and 20 real candidates, through the normal job pipeline on the test database, with `mistral-small-2603`. Measured from the usage records.

**First attempt: 16 of 20 candidates, and 13 of 29 CV answers rejected.** The vacancy and the CV prose read well. The failures were not the model's fault. They came from three faults in the design, which the fake could never have shown:

1. **Alternatives became separate requirements.** The vacancy asked for "5+ years with AWS, Azure, or GCP". The profile returned AWS, Azure and GCP as three required skills of five years each, and the same for three infrastructure tools. A "strong match" therefore had ten years of all three clouds: not a person anyone would believe.
2. **Skill names that contain each other.** The profile listed both "AWS" and "AWS CDK". A candidate who had "AWS CDK" but not "AWS" could never pass the check "must not mention AWS", because naming one names the other. Three of the four failed candidates were of this kind: impossible by construction.
3. **Activities as skills.** For adjacent roles the model returned items such as "monitoring", "troubleshooting" and "proactive measures". The rule "name a skill only in the jobs where it was used" cannot be kept for words that any CV for that job uses everywhere.

**What was changed:**

- A requirement is now a group: `{"any_of": ["AWS", "Azure", "GCP"], "min_years": 5}`. One alternative meets it. A strong match has one, sometimes a second for a shorter time.
- The profile drops any skill name that contains another, or is contained in one (whole words only: "Go" and "Google" do not clash).
- The rule about naming a skill only in its own jobs now covers the vacancy's skills only. The everyday skills of another job may appear anywhere.
- Someone in the vacancy's own line of work now has at least one skill in every job. A cloud engineer's job with no skill to name was hard to write.
- The CV prompt lists, per job, what not to name there, instead of leaving that to be worked out. The profile prompt asks for named things, not activities, and explains alternatives.
- Both prompts became version 2. Version 1 produced results only in throwaway test databases, so it was replaced rather than kept.

**Second attempt, same setup: 20 of 20 candidates, every CV usable on the first answer.**

| | Calls | Tokens in | Tokens out | Estimated cost | Average latency |
| --- | --- | --- | --- | --- | --- |
| Vacancy | 1 | 470 | 603 | $0.00043 | 4.5 s |
| Vacancy profile | 1 | 986 | 497 | $0.00045 | 2.8 s |
| CVs | 20 | 12,608 | 7,925 | $0.00665 | 3.0 s |
| **Total** | **22** | | | **$0.0075** | |

- The 20 CVs took 19.5 seconds with four calls at a time. No rate-limit errors.
- **$0.00033 per CV**, so about 3.5 cents for 100 candidates. An extrapolation, not yet measured at that size.
- The profile for this vacancy: `AWS | Azure | GCP` (5 years), `Terraform` (3 years), `Python | Bash | Go`, `Docker | Kubernetes`, `Prometheus | Grafana | Datadog`, with four nice-to-haves. All named things.
- Read by eye: one strong, one partial and one adjacent CV. The prose is fluent and specific. The strong match has ten years of GCP with Terraform, Go, Docker and Prometheus, which is believable.
- **One artefact is visible:** a partial match who lacks every cloud is a "Cloud Engineer" whose CV never names a cloud ("cloud infrastructure using industry-leading tools"). That follows from the rule that a missing skill must not be mentioned. A real CV would not read like that.
- The first attempt cost about one cent as well. Total real spend on this stage: about 2 cents.

## Still open

- **One vacancy, one sector, 20 candidates.** That is all the real evidence so far. Other sectors may give vaguer skills (a nurse or a teacher has fewer named tools), and a pool of 100 has not been run.
- **The real run went through the API and the job runner, not through a browser.** The browser tests still use the fake.
- **The selection script in stage 5 needs the same idea of alternatives.** A hard requirement "AWS" would wrongly drop an Azure engineer when the vacancy accepts either. To be decided with the author before stage 5 starts.
- **Cost of 100 candidates is still an estimate**: at the measured $0.0003 per CV, about 3 cents plus retries. To be measured on a real run.
- **Rate limits.** Four calls at a time is a guess. On a low tier, 100 CVs may be slow.
- **The pool is easier than real life**, by design of the checks above: a candidate's CV never mentions a skill they lack. The README must say so (PRD section 14).
- **Skill names are matched as whole words.** "Java" does not match "JavaScript", but a model that writes "Azure" where the blueprint says "Microsoft Azure" passes the check. That is harmless for ground truth and matters for scoring in stage 6.
- **Selection script results and lists** will also need the out-of-date mark when candidates are regenerated; they do not exist yet.
