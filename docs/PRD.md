# RecruitDesk: PRD

A demo web app that shows how an LLM (Mistral) can streamline the first stages of recruitment: writing a vacancy, creating a pool of fictional candidates, turning the vacancy into screening criteria, and proposing a long list and short list with a written reason for each candidate.

**Status:** draft, for building with Claude Code. Verify current Mistral model names, structured-output support, rate limits and prices, and Railway (or other host) limits before each stage.

**This is a demo, not a product.** All candidates are fictional. Nothing here should be used to make real hiring decisions.

---

## 1. Purpose

- Show a complete, believable AI-assisted recruitment flow end to end: vacancy, candidates, criteria, long list, short list.
- Show how to use an LLM in HR **responsibly**: the model proposes, a person decides; scoring is explainable; claims are checked by code; and protected attributes never reach the scoring step.
- Be small enough to build in a few days and deployable online, so it can be shown to anyone with a link.

**The question the project works through:** how can an LLM help recruiters screen faster, while every claim it makes about a candidate can be checked, and the person stays in charge?

## 2. Users

One role: **recruiter**. There is no login for individuals. A visitor enters an access code (F0) and gets a private workspace (section 11). The target audience of the demo is someone evaluating the app, for example a hiring manager or a client of an AI consultancy.

## 3. Scope

**In scope**
- Generate a vacancy from a few choices, then review, edit, cancel or submit it
- List and open submitted vacancies
- Generate 1 to 100 fictional candidates (CVs) per vacancy
- Generate and edit a selection script (screening criteria) per vacancy
- Generate a long list and a short list with a written reason per candidate
- Generate interview questions for the short-listed candidates (F8)
- An **access-code gate** in front of the whole app: 10 five-letter codes, each usable 20 times (F0)
- Deployment online with cost and abuse protections
- An evaluation that measures the quality of the lists against known ground truth

**Out of scope**
- Real candidate data, CV uploads, email sending, calendar booking
- User accounts, roles, multi-tenant administration
- Applicant tracking features (pipeline stages, notes, offers)
- Fine-tuning models

## 4. Concepts and terms

| Term | Meaning in this app |
| --- | --- |
| Vacancy | A job description with a title, sector, seniority, work mode and structured sections |
| Draft | A vacancy that has been generated but not yet submitted |
| Submitted vacancy | A vacancy that was submitted and now appears under "Submitted vacancies" |
| Candidate | A fictional person with a CV, generated for one vacancy |
| Selection script | The screening criteria for one vacancy: keywords, required years of experience, and for each whether it is a hard or soft requirement. This is a set of criteria, not a phone-call script. Interview questions are a separate item (F8). |
| Interview questions | Questions for the interview stage, generated after the short list exists: a core set shared by all short-listed candidates, plus follow-up questions per candidate |
| Long list | The best-matching subset of candidates, about 30%, at most 10 |
| Short list | The very best subset, about 10%, at most 4, always a subset of the long list |

## 5. User flow

```
[Enter access code] -> private workspace created (F0)

[Generate vacancy] -> dialog -> spinner -> "Your vacancy is ready to be viewed"
        -> review and edit -> [Cancel vacancy] (confirm, deletes all)  or  [Submit vacancy]

[Submitted vacancies] -> list (or "No vacancies have yet been submitted")
        -> open one -> Edit vacancy | Generate candidates | Generate selection script
                      | Generate long-list | Generate short-list
                      | Generate interview questions (on the short-list page)
```

Both top-level buttons ("Generate vacancy" and "Submitted vacancies") are always visible.

## 6. Functional requirements

### F0 Access gate (access codes)
The app will be online and calls a paid model, so nothing is reachable without a valid access code.

- **Entry screen.** On a first visit the app shows only a code entry screen. Input is case-insensitive and ignores surrounding spaces. Nothing else is reachable without a valid session.
- **The codes.** There are **10 codes of 5 letters each** (uppercase A to Z without I and O, to avoid confusion with 1 and 0). They are generated randomly with Python's `secrets` module by a script, `scripts/manage_codes.py create --count 10`, which prints them **once** to the terminal. The developer keeps them in a password manager.
- **Never in Git.** The codes are never written to the repository, this PRD, test files, CI configuration or logs. They exist only in the developer's password manager and, as keyed hashes, in the production database (see below). Tests use obviously fake codes. The generator script writes no file.
- **Usage limit.** Each code can be redeemed **20 times**. One redemption means one new session started with that code. Reloading the page, or coming back while the session is still valid, does not use up another redemption. The counter is increased atomically in the database (a single conditional update), so simultaneous requests can never push a code over 20.
- **Messages.**
  - Not a valid code: "That code is not valid. Check the code and try again."
  - Code used up: "This access code has been used the maximum number of times. Please contact the developer to get a new code." with a contact link (configurable, for example the LinkedIn profile).
- **Brute-force protection.** Failed attempts are limited per IP (for example 10 failures per 15 minutes, followed by a temporary lockout with a clear message) and there is a global ceiling on failed attempts per hour. With roughly 8 million possible codes and only 10 valid ones, guessing is impractical only if this limit exists. Showing a different message for a used-up code confirms that the code exists. That is accepted, as requested, and the rate limit contains it.
- **Session.** A valid code creates a workspace and a signed session cookie (HttpOnly, Secure, SameSite=Lax) that lasts as long as the workspace (for example 24 hours of inactivity). Every API call requires a valid session, otherwise it returns 401 and the UI shows the code screen. The workspace records which code created it.
- **Storage.** Codes are stored as keyed hashes (HMAC-SHA256 with a secret pepper from an environment variable), together with a label (`c01` to `c10`), the use count, the limit, and the time of last use. A leaked database alone does not reveal the codes.
- **The public code.** One of the ten codes is shared publicly, on the developer's LinkedIn profile, so that anyone can try the app. It will be used by strangers, and the limit of 20 bounds that exposure. When it is used up, the developer creates a new code and updates the profile.
- **Bounded spend.** Each session has its own limits (a maximum number of vacancies, candidates and jobs). The worst-case spend is therefore bounded: 10 codes × 20 uses × the cost of a maximum session. Compute this figure from the usage records and state it in the README. The daily global spend cap (section 11) is a second protection.
- **Developer tooling** (a command-line script, no admin web page):
  - `create --count N`: generate and register N new codes and print them once with their labels.
  - `status`: show per label the uses, the limit, the remaining uses and the last use. It never prints codes.
  - `extend --label c03 --uses 20`: add redemptions to a code.
  - `disable --label c03`: block a code immediately.
- **Acceptance criteria.**
  - A valid code starts a session and raises the code's use count by exactly one.
  - Reloading or returning within the session does not raise it.
  - The 21st redemption of the same code is refused with the "used up" message.
  - 25 simultaneous redemptions of a code with one use left give exactly one success.
  - A lowercase or space-padded code works.
  - An invalid code gives the "not valid" message and counts towards the attempt limit.
  - After too many failed attempts the IP is locked out for a period, and the lockout message does not reveal anything about the codes.
  - Without a session, every API route returns 401.
  - No submitted code appears in logs, and CI fails if a codes file is tracked by Git.

### F1 Generate vacancy
- A dialog with:
  - **Sector** (dropdown): for example IT and software, healthcare, finance, logistics, public sector, education, retail, energy, engineering and manufacturing, marketing, legal.
  - **Seniority** (checkboxes, at least one): junior, medior, senior, lead.
  - **Work mode** (checkboxes, at least one): office-based, home-based, hybrid.
  - **Vacancy title** (text, required, length-limited).
  - Additions I suggest: an optional **company name** (a fictional one is generated if left empty), and an optional free-text field **"Anything to emphasise"** (limited length).
- Submitting starts a background job. While it runs the dialog shows a **spinner** with a short status message, and the user can close the dialog without losing the job.
- Failures show a clear message with a Retry button. A job that was interrupted by a restart is marked as such and can be retried.
- The model returns **structured sections**, not one blob: title, company introduction, role summary, responsibilities, required qualifications, nice-to-haves, what we offer, location and work mode. Structure is needed so that later steps (candidates, criteria) can use it.
- Guardrails: the vacancy must not include discriminatory requirements (age, gender, nationality, and so on). The prompt forbids them, and a simple code check flags a short list of obvious terms for review.

### F2 Review, edit, cancel, submit
- When the job finishes, the spinner stops and a button appears: **"Your vacancy is ready to be viewed"**.
- The review view shows each section in an editable field. Edits are saved as a new version of the draft. The original generated text stays available ("Reset to generated").
- **Cancel vacancy** is destructive: a confirmation dialog states exactly what will be deleted. On confirmation the draft and all related data are deleted and the user returns to the start.
- **Submit vacancy** validates that required sections are not empty, changes the status to submitted, and moves the vacancy to "Submitted vacancies".

### F3 Submitted vacancies
- If there are none: "No vacancies have yet been submitted".
- Otherwise a list (title, sector, seniority, work mode, submitted date, status chips such as "20 candidates", "script ready", "long list ready").
- Opening a vacancy shows its text and the actions: **Edit vacancy** (same editor as F2), **Generate candidates**, **Generate selection script**, **Generate long-list**, **Generate short-list**. **Generate interview questions** sits on the short-list page (F8).
- Actions whose prerequisites are missing are visible but disabled, with the reason shown ("Generate candidates first").
- **Stale data:** if a vacancy is edited after candidates, a script or lists exist, those items are marked **out of date** with a warning, and regenerating them is a deliberate action.

### F4 Generate candidates
- The user enters a number from **1 to 100**. The limit is enforced on the server as well.
- Candidates are created in steps, which I recommend instead of asking the model for "100 CVs":
  1. **Vacancy profile, by the model.** One call per vacancy version extracts the vacancy's requirements, plus a few adjacent and unrelated roles. A requirement is one or more alternative skills with the years asked for: "5 years with AWS, Azure or GCP" is one requirement that any one of the three meets. Skills are short named things (a tool, technology, method or certificate), and no skill name may contain another. The blueprints are built from this.
  2. **Blueprints, by code.** Code samples a blueprint per candidate: a fictional name, seniority (sometimes above or below the vacancy), a dated job timeline, the skills used in each job, and a **match category**: strong match, partial match, adjacent role, or weak match, in a fixed distribution (15%, 35%, 30%, 20%, with at least one strong match). Years of experience per skill follow from the timeline. This guarantees variety and means the **ground truth is known**.
  3. **CV writing, by the model.** The model writes the prose of a CV for each blueprint (profile, job titles, company names, highlights, education), in batches with limited concurrency. Dates, the skills per job, languages and contact details are added by code. So the dated employment history in a CV is exactly the planted one. An answer that names a skill the candidate does not have, names a skill in a job where it was not used, or contains personal details is treated as invalid output.
- Contact details are clearly fictional: email addresses on a reserved domain (`example.com`), phone numbers from the range Ofcom reserves for drama (`+44 7700 900xxx`), and a "synthetic data" label in the UI.
- Progress shows as "x of N created". The candidates are stored on a **separate page per vacancy** (searchable, sortable, with a CV detail view).
- Regenerating candidates replaces the existing ones, with a confirmation dialog. The long list and short list made from the old candidates are deleted with them, because they name people who no longer exist. The dialog says so.
- The CV text must not include birth date, photo, gender, marital status or nationality.

### F5 Generate selection script
- A dialog opens with a **proposal from the model**, based on the vacancy text: a list of items. Each item has one or more **keywords** (for example "Microsoft Azure"), a **required number of years of experience** where it makes sense, and a flag: **hard** or **soft** requirement. Each item also carries a short reason: the sentence from the vacancy it is based on.
- **Alternatives.** An item may hold up to four keywords that can replace each other: "AWS / Azure / GCP, 5 years, hard". A candidate meets the item with any one of them. Years are not added up across alternatives: one alternative must reach the years on its own.
- **The reason is checked by code.** The model is asked to quote the vacancy. Code looks the quote up in the vacancy text. A reason that is not found is kept, and shown as not found in the vacancy.
- **Only the required qualifications make a proposed item hard.** Code finds the section of the vacancy each quote comes from. An item the model proposed as hard, but that is quoted from the responsibilities, the role summary or the nice-to-haves (or not found at all), becomes soft, with a note that says so. The recruiter can still make any item hard.
- The proposal is made by a background job, with a spinner. A proposal is not saved as the script. A waiting proposal for the current vacancy text is reused when the dialog is opened again.
- The user can edit the keywords, change the years, flip hard or soft, remove items, and add new ones. Buttons: **Cancel** (nothing saved) and **Submit** (saves the script).
- A saved script is linked to the version of the vacancy it was made from. If the vacancy is edited afterwards, the script is marked out of date. Submitting again saves it for the current text.
- Definitions: a **hard** requirement must be met for a candidate to be listed (unless there are too few candidates who meet them, in which case this is shown as a flag). A **soft** requirement adds to the score but is not required. Both are applied in one function.

### F6 Long list and short list
- Both are available only when the vacancy, the candidates and a script exist.
- **One screening run produces both lists.** "Generate long-list" and "Generate short-list" each make sure a current run exists and then show their list. If the candidates or the script are out of date, both actions are disabled and say which to redo first.
- **Sizes:** long list = `min(10, max(1, round(0.30 × N)))`, short list = `min(4, max(1, round(0.10 × N)))`, where N is the number of candidates. `round` means round half up, computed with integer arithmetic (not Python's built-in `round`, which rounds half to even), so N = 15 gives a long list of 5 and N = 25 gives a short list of 3. The short list is always a subset of the long list. For example: N = 100 gives 10 and 4, N = 20 gives 6 and 2, N = 5 gives 2 and 1.
- **Method (two stages):**
  1. **Deterministic pre-scoring, by code** on a blind version of each CV: keyword matches, years of experience per keyword computed from the dated employment history, and hard-requirement checks.
  2. **LLM assessment** of the strongest candidates (for example the top 2 × the long-list size, or everyone if N is small). The model reads the blind CV, the vacancy and the script and returns a structured assessment: fit score, strengths, concerns, and a paragraph of reasoning. It is explicitly allowed to weigh more than keywords and years, such as the relevance of past roles and sectors, career progression, and transferable skills.
- **Evidence check, by code:** every keyword the model says it found must actually appear in that CV, and every number of years it states is compared with the computed value. Unsupported claims are removed from the text and flagged. This is the same principle as resolving citations in code.
  - The model is not given the computed facts: it reads the CV itself, and code checks what it says.
  - A strength names the keywords it rests on, a concern the keywords the candidate lacks, so both can be checked. A sentence of the reasoning that names a keyword the CV does not contain, or years that match nothing computed, is removed.
  - The numbers shown to the recruiter are always the computed ones.
- Final ranking combines the deterministic score and the LLM score with a documented, configurable weighting.
- Re-running with the same inputs should give a very similar list. Use low temperature, a pinned model version, and a fixed prompt version.

### F7 Output of the lists
- Each entry shows **name, phone number, email address**, then **a paragraph explaining why** the candidate is on the list: keywords found in the CV, years of experience, and other points the model found relevant. Concerns are shown too ("no experience with X").
- The detail view shows the evidence: which parts of the CV the claims come from.
- A short, always-visible notice: "Suggestions to support a recruiter. A person decides."
- Optional: export the list as CSV.

### F8 Interview questions
An add-on for the step after screening. It lives on the short-list page, because that is the moment a recruiter prepares interviews, and because the questions build on the assessments.

- **Available only when a current short list exists.** Otherwise the button is visible but disabled, with the reason shown ("Generate the short list first").
- **Two parts, generated by one background job** with progress ("x of N candidates"):
  1. **Core questions** for the vacancy (about 6 to 8), derived from the vacancy and the selection script. Every short-listed candidate gets the same core questions, so interviews can be compared fairly.
  2. **Follow-up questions per short-listed candidate** (about 3 to 5), derived from the blind CV and that candidate's assessment: strengths to verify and concerns to probe ("no experience with X").
- **Structured output.** Each question has the question text, what it is meant to find out, and a link to its source: a selection-script item, or a strength or concern from the assessment. The UI shows the source next to the question.
- **Built on checked claims only.** Follow-up questions use the assessment after the evidence check (F6), so a question never rests on a claim that was removed as unsupported. A code check confirms that every link points to an existing script item or assessment point; questions with a broken link are dropped and flagged.
- **Blind.** The model gets the anonymised CV, as in F6. The candidate's name is joined back only for display.
- **No discriminatory questions.** The prompt forbids questions about age, gender, family or pregnancy plans, health, religion, nationality or origin, and the same kind of code check as in F1 flags obvious terms for review.
- **Editing.** The recruiter can edit, remove and add questions. The generated version stays available ("Reset to generated").
- **Stale data.** If the vacancy, the script or the lists change, the questions are marked out of date. Regenerating replaces them, with a confirmation dialog.
- **Limits.** The job costs at most 1 + 4 model calls (the short list has at most 4 entries). It counts towards the per-workspace limits and the usage records.
- The notice from F7 also applies here: "Suggestions to support a recruiter. A person decides."
- **How the links work:** the model gets numbered references (S1 for a script item, P1 for a strength, C1 for a concern) and names one per question. Code drops a question whose reference was not offered, and reports how many were dropped. After an edit, the server looks each source up again.
- **Generating again** replaces all questions, including edits, after a confirmation. Regenerating candidates deletes their follow-up questions.
- Optional: print or export the questions per candidate.

## 7. Responsible-AI design (my additions)

Recruitment is a sensitive use of AI. In the EU it is treated as high-risk, so the demo should show good practice, not only convenience.

- **Blind screening.** Name, contact details and anything personal are removed before the scoring step. The model sees an anonymised CV, and the contact details are added back only when the list is shown. This mirrors the privacy gate in Muni Mailbox.
- **No protected attributes.** CVs contain none, vacancy generation avoids discriminatory requirements, and a check flags obvious problems.
- **Explainable and checkable.** Every reason is backed by evidence from the CV, and unsupported claims are dropped.
- **A person decides.** The wording and UI make clear that the lists are suggestions.
- **Consistency test (see section 10).** The same CV with a different name must get the same assessment.

## 8. Technology

| Layer | Choice | Note |
| --- | --- | --- |
| Backend | Python 3.12, FastAPI, async | As in earlier projects |
| Model access | Official Mistral Python SDK, direct, no framework | Contrast with IntakeFlow, which uses LangChain and LangGraph |
| Models | A smaller Mistral model for CV writing and vacancy text, a stronger one for assessment | Pin exact model versions. Mistral is an EU provider, which is a useful point for GDPR-minded customers |
| Structured output | JSON schema with Pydantic validation, one retry on invalid output | Verify the current structured-output feature in the SDK |
| Database | PostgreSQL with SQLAlchemy 2 (async) and Alembic | |
| Background jobs | Database-backed jobs in the same process, with status polling from the UI | Enough for a demo. Mark interrupted jobs on restart |
| Frontend | React with TypeScript (Vite) | Dialogs, spinner and state are easier to show clearly. HTMX is an alternative if speed matters more |
| Hosting | Railway (web service plus PostgreSQL) | Already used for Family Scrum. Keep it to a single service |
| Tests and CI | pytest, Playwright for a few browser tests, ruff, mypy, GitHub Actions | Mistral replaced by a fake in all tests |
| Observability | Structured logs and per-call usage records (model, tokens, latency, estimated cost) | Same approach as IntakeFlow |

## 9. Data model (outline)

- **access_code**: id, label (c01 to c10), code_hash (HMAC-SHA256 with a pepper), uses, max_uses (default 20), disabled, last_used_at. The codes themselves are never stored.
- **failed_attempt**: ip_hash, attempted_at (for rate limiting; the submitted code is not stored)
- **workspace**: id, access_code_id, created_at, last_seen_at (for clean-up)
- **vacancy**: id, workspace_id, status (generating, draft, submitted, failed), parameters (sector, seniority[], work_mode[], title, company, emphasis), sections (JSON), generated_sections (JSON, for "reset"), version, timestamps
- **candidate**: id, vacancy_id, blueprint (JSON, includes match category), cv (JSON), cv_text, name, email, phone
- **selection_script**: id, vacancy_id, vacancy_version, items (JSON: keyword, min_years, kind hard or soft, reason, enabled)
- **assessment**: id, vacancy_id, script_id, candidate_id, deterministic_score, llm_score, final_score, rationale, evidence (JSON), flags, in_long_list, in_short_list, run_id
- **interview_question_set**: id, vacancy_id, script_id, run_id, candidate_id (empty for the core set), items (JSON: question, purpose, source kind and source reference), generated_items (JSON, for "reset"), flags, prompt_version, out_of_date
- **job**: id, type, vacancy_id, status (queued, running, done, failed, interrupted), progress, error_kind, timestamps
- **usage_record**: call_type, model, input_tokens, output_tokens, latency_ms, estimated_cost

## 10. Evaluation (what makes this more than a demo)

Because candidates are built from known blueprints, the quality of the lists can be measured. Report the results in the README, including the unflattering ones.

| Measure | Method |
| --- | --- |
| Short-list quality | Share of short-list entries that are planted strong matches (precision), and share of strong matches that reached the long list (recall) |
| Hard-requirement compliance | No listed candidate fails a hard requirement without a flag |
| Evidence accuracy | Share of claimed keywords and years that check out against the CV text |
| Deterministic vs LLM stage | Compare: keywords only, LLM only, combined. Report where they differ |
| Consistency | Run the same input several times and measure the overlap of the lists |
| Name-swap fairness test | Same CV with different fictional names must give the same score and reason within a small tolerance |
| Vacancy quality | A simple rubric (all sections present, no discriminatory terms, matches the chosen parameters), checked in code where possible |
| Interview-question quality | A rubric checked in code: every question links to an existing script item or assessment point, no discriminatory terms, core questions identical for all candidates, and follow-ups unchanged under the name swap within a small tolerance |
| Cost and latency | Per vacancy, per 100 candidates, per list and per set of interview questions, from the usage records |

Evaluation is a script that writes a report, not a test. Fakes that answer from the ground truth validate the evaluation code itself.

## 11. Deployment, cost and abuse protection

A public link to an app that calls a paid model needs protection.

- **Access:** the access-code gate in F0: 10 five-letter codes, 20 redemptions each, not stored in Git, one of them public on LinkedIn. The pepper and any other secrets are environment variables only.
- **Workspaces:** each visitor gets a private workspace tied to a cookie. Workspaces and all their data are deleted after a time limit, for example 24 hours of inactivity, plus a "Reset demo" button.
- **Limits:** per-workspace and per-IP rate limits, the 100-candidate cap enforced on the server, a maximum number of vacancies per workspace, and request size limits.
- **Budget:** a **daily global spend cap** computed from the usage records. When it is reached, generation is disabled with a clear message. Also set a spending limit or alert on the Mistral account.
- **Secrets:** the Mistral API key and database URL only as environment variables, never in the repository, logs or chat.
- **Health check, migrations on start, one-command deploy, and a short runbook** in the README.
- Check the current Mistral rate limits. The free tier is tightly limited and may slow candidate generation, so batching and limited concurrency matter.

## 12. Non-functional requirements

- **Responsiveness:** the UI never blocks. Long jobs show progress and can be left and returned to.
- **Accessibility:** dialogs trap focus and can be closed with Escape, controls are labelled, and the spinner has a text alternative.
- **Reliability:** idempotent jobs, retries with backoff on model calls, validated structured output, and clear error messages.
- **Privacy:** no real personal data anywhere. Logs contain ids and counts, not CV text.
- **Language:** the UI and all generated content in English.

## 13. Stages

Each stage ends with working software, tests and a short note on what was learned.

0. **Skeleton.** Repository layout, `uv`, Docker Compose, database and Alembic, health endpoint, empty Vite app, CI.
1. **Access gate.** The access-code gate and `manage_codes.py` (F0, built first so everything after it sits behind a session), session cookie, workspace, failed-attempt limits, code entry screen.
2. **Vacancy generation.** Mistral client behind an interface with a fake, prompt files, background job and spinner, usage records, the generate dialog, structured vacancy sections.
3. **Review, edit, cancel, submit.** Editor, versions, reset, destructive-action confirmation, submitted list and empty state.
4. **Candidates.** Blueprint sampler, CV generation in batches with progress, per-vacancy candidate page, regeneration with confirmation.
5. **Selection script.** Proposal from the model, editing dialog, hard and soft logic, stale-data handling.
6. **Long list and short list.** Blind CVs, deterministic scoring, LLM assessment, evidence check, sizes, output page.
7. **Interview questions.** Core and follow-up questions (F8), source links and link check, editing, stale-data handling.
8. **Evaluation and hardening.** Evaluation scripts and report, name-swap test, daily spend cap, workspace clean-up.
9. **Deployment and write-up.** Railway deployment, README with measured results, honest limits, screenshots.

Per-workspace caps and usage records are added in the stage where each billable call first appears, not left to stage 8.

Stages 0 to 4 already give a presentable demo. Stage 6 is where the project becomes interesting.

## 14. Honest limits to state in the README

- A demo with synthetic candidates. Real CVs are messier, so quality figures are an upper bound.
- LLM-generated CVs share patterns, even with blueprints. The test pool is easier than a real one.
- Results depend on the model version and can change when models are updated.
- AI in recruitment is a high-risk area. This demo shows safeguards but is not a compliant production system.
- State plainly what was run against the real Mistral API and what was tested with fakes only.
- The public access code can be used up by anyone, which is by design. A code is a light protection against casual abuse and runaway cost, not real authentication.

## 15. Skill coverage map

| Skill from AI engineering vacancies | Where in the project |
| --- | --- |
| LLM integration with a provider SDK | Mistral client, structured output, retries |
| Prompt engineering and structured output | Vacancy sections, CV writing, criteria proposal, assessments |
| Agents and workflows | Multi-step pipeline with deterministic and LLM stages |
| Reliability, hallucination control | Evidence check, validation, low temperature, pinned versions |
| Responsible AI, privacy, fairness | Blind screening, name-swap test, human decides |
| Evaluation of LLM output | Ground-truth blueprints, precision and recall, consistency |
| Cost and latency awareness | Usage records, budget cap, model choice per step |
| Product thinking | Clear flows, confirmations, empty states, disabled actions with reasons |
| Deployment | Railway, secrets, health check, runbook |

## 16. Where this goes beyond your brief

Changes and additions I made, so you can accept or reject each one:

1. Two-step candidate creation (code blueprints, then model-written CVs), so there is variety and known ground truth.
2. Structured vacancy sections instead of free text.
3. Hard and soft requirements are defined precisely, including what happens when too few candidates meet them.
4. A formula for list sizes, including small candidate pools, and a rule that the short list is a subset of the long list.
5. A two-stage ranking, plus an evidence check that drops claims not found in the CV.
6. Blind screening, a name-swap fairness test, and a notice that a person decides.
7. "Out of date" handling when a vacancy changes after candidates, script or lists exist.
8. Jobs, progress and interruption handling for long generation runs.
9. Cost and abuse protection for a public deployment: access code, private workspaces with expiry, rate limits, daily spend cap.
10. An evaluation script and report.
11. Details of the access gate: what counts as a "use" (a new session, not a page load), atomic counting, brute-force limits, hashed storage with a pepper, a management script, and a computed worst-case spend per code.
12. Interview questions for short-listed candidates (F8).
13. A vacancy profile call, and job timelines built by code, so that the planted years of experience per skill are exact (F4).
14. Alternatives in a script item, and a check in code that each item's reason is a quote from the vacancy (F5).

## 17. Open decisions

Decided (2026-10-13):

- "Selection script" is a criteria set. Interview questions are a separate add-on (F8).
- A script item may hold alternative keywords; any one of them meets it, and years are not added up across them (F5).
- Only an item quoted from the required qualifications can be proposed as hard (F5, decided after the stage 6 comparison).
- The assessment model is `mistral-small-2603`: the medium model gave the same lists at ten times the price (stage 6 comparison).
- The two calls made once per vacancy, the vacancy profile and the script proposal, use `mistral-medium-2604`: with the small model they read the vacancy differently, and the script split alternatives (stage 6).
- Frontend: React with TypeScript (Vite).
- Access gate: one "use" means one new session.
- Contact link shown when a code is used up: the developer's LinkedIn profile, set through an environment variable.
- Language of the UI and content: English only.
- Stages: the ten stages in section 13 (0 to 9).
- List sizes: round half up, with integer arithmetic (F6).
- Daily spend cap: $2.00 by default, set through `DAILY_SPEND_CAP_USD`, from the estimated cost in the usage records (stage 8).
- Equal final scores are broken by the ranking computed by code, so the same input always gives the same lists (stage 8).
- "Reset demo" deletes the workspace's vacancies but keeps its session and its limits (stage 8).
- Per-IP rate limit: at most 5 new sessions per IP address per hour (`MAX_SESSIONS_PER_IP_PER_HOUR`), checked before a code use is counted. Visitors behind one network share it (stage 8).

Still open:

- Whether to show different messages for an invalid and a used-up code (specified as different, as requested, with rate limiting to contain the leak).
- Whether to include CSV export, and print or export of interview questions.
