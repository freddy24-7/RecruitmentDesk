# Stage 7: Interview questions

Date: 2026-10-14

## What was built

- **"Generate interview questions"** on the short-list page. When there is no current short list, the button stays visible but disabled, with the reason.
- **One background job** makes the core questions for the vacancy and the follow-up questions for each short-listed candidate, with progress as "x of N question sets made".
- **Every question names what it is based on**: an item of the selection script for a core question, a strength to verify or a concern to probe for a follow-up. The page shows that source with each question.
- **Editing per set:** change, remove and add questions; "Reset to generated" after a confirmation.
- **Generating again** replaces all questions, including edits, after a confirmation that says so.
- **Seventh migration** (`0007`): the `interview_question_set` table.

## How the rules are kept

- **Built on checked claims only.** A follow-up question can only refer to a strength or concern that survived the evidence check of stage 6; those are the only points offered to the model.
- **Links are checked by code.** The model gets numbered references (`S1` for script items, `P1` for strengths, `C1` for concerns) and must name one per question. A question that names a reference that was not offered is dropped, and the page says how many were left out. When the recruiter saves edits, the server looks the source up again; an unknown reference makes the question the recruiter's own. What the browser sends for the source text is ignored.
- **Blind.** The model reads the anonymised CV, as in stage 6. The candidate's name is joined back only when the questions are displayed.
- **Protected attributes.** The prompts forbid questions about age, gender, family or pregnancy plans, marital status, health, religion, nationality, origin or sexual orientation. A check in code flags obvious terms ("how old", "children", "where are you from", "your health") for review, also after every edit. It flags; it does not block.
- **Out of date.** A set records the vacancy version, the script revision and the screening run it was made from. If any of those changed, the questions are marked out of date. Regenerating candidates deletes the follow-ups for the people who no longer exist; the core set stays, marked out of date.

## Decisions and why

- **Core questions are the same for every short-listed candidate**, so interviews can be compared: a structured interview.
- **Follow-ups are per candidate**, on what the assessment found: strengths to verify with examples, concerns to probe openly.
- **The flag list was narrowed for this use.** Words such as "partner" and "health" on their own would flag ordinary questions ("How did you partner with the security team?", a nurse asked about health care). The check looks for personal phrases instead ("your health", "sick leave").
- **The small model**, with at most five calls per run (one core set, at most four follow-up sets).
- **Limit:** 10 runs per workspace, one job at a time, three tries per job.
- **Print or export** of the questions is not built (an optional item in the PRD).

## What was seen in practice

- 739 backend tests pass, 96 frontend tests and 8 browser tests. Lint, types and the build are clean.
- **Tests that break the system on purpose:** a model that invents a source reference (the question is dropped and reported), a model that asks "How old are you, and do you have children?" (flagged with both terms), and CVs whose owners' names and contact details must not reach the model.
- **A run that fails part-way** is retried and only makes the sets still missing.
- **A one-off stall** of the frontend test runner made the first run time out; it passed when run again, with no code change.
- **Real model, first run (2026-10-14, `mistral-small-2603`, on a fresh real pool):** three calls, all usable on the first answer, 8 seconds, $0.0013 for the questions. No question was dropped for a bad reference and none was flagged. The core questions were open, about real situations, one per script item. The follow-ups verified strengths with details from the candidate's own CV ("…reducing deployment times by 45%. What was the most complex pipeline you built?").
- **What that run found, and what was changed:**
  - **A false concern reached the questions.** The script asked for "AWS or Azure"; the candidate had AWS. The assessment still listed "lacks direct experience with Azure, which is a required platform", the evidence check kept it (Azure was indeed not in the CV), and the follow-up told the candidate "The role requires experience with Azure". Fixed in the stage 6 evidence check: a concern whose keywords are all alternatives of a requirement the candidate already meets is removed and flagged ("Azure: AWS meets the same requirement"). This also cleans the lists.
  - **Reference codes in the text** ("…as stated in P1"). Both prompts are now version 2 and ask not to mention references.
- **Second real run with the fixes, on another fresh pool:** the evidence check removed 8 concerns about a missing alternative across the 12 assessed candidates, so the short-listed candidates had no false concerns left. The core questions carried no reference codes in two runs. The follow-up purposes still did now and then ("…tools mentioned in P1"): the small model does not always follow that instruction.
- Estimated real spend for this stage: about 3 cents (two pools with screening, three runs of questions).

## Still open

- **A reference can exist and still be the wrong one.** In the first real run a question about Grafana dashboards cited a concern about missing monitoring tools. Code checks that a reference was offered, not that it fits the question.
- **Reference codes still appear now and then in follow-up purposes.** Removing them by code was considered and left out: a code such as "S3" can also be a real keyword (the AWS storage service).
- **Not every concern gets a question.** The prompt asks for 3 to 5 follow-ups, not one per point.
- **Two runs on cloud engineer vacancies are all the real evidence.** Other sectors, and how often a real model asks something it should not, are untested.
- **The protected-attribute check is a short list of terms.** A question that is discriminatory in other words passes it.
- **No print or export.**
