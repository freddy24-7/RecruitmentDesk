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
- **Not yet run against the real model.**

## Still open

- **The quality of real questions is unknown**: whether they are specific, open and fair, and how often a real model invents a reference or asks something it should not.
- **The protected-attribute check is a short list of terms.** A question that is discriminatory in other words passes it.
- **No print or export.**
