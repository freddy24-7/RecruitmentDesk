# Stage 6: Long list and short list

Date: 2026-10-13

## What was built

- **One screening run produces both lists.** "Generate long-list" and "Generate short-list" each make sure a current run exists and then show their list.
- **Step 1, by code, for every candidate:** each keyword of the script is looked up in the blind CV, its years are computed from the dated jobs that mention it, and the hard and soft requirements are applied.
- **Step 2, by the model, for the strongest candidates** (twice the long-list size): a fit score, strengths, concerns and a paragraph of reasoning, from the anonymised CV, the vacancy and the script.
- **The evidence check, by code:** claims the CV does not support are removed or corrected, and flagged.
- **The final ranking** combines both stages with a configurable weight (half and half by default).
- **The output pages:** name, phone and email, the paragraph explaining why, strengths, concerns and flags per entry; a detail view with the evidence; and the notice "Suggestions to support a recruiter. A person decides." on every list screen.
- **Sixth migration** (`0006`): the `assessment` table.

## How the rules are kept

- **Blind screening (rule 3).** The facts are computed on the anonymised CV, and the model gets only anonymised text. Our generated CVs hold no name by construction, but `app/screening/blind.py` still removes the candidate's name, email and phone, and anything that looks like an email address, a URL or a phone number. Contact details are joined back in one place only: the route that serves the lists.
- **Facts by code (rule 4).** Years come from `keyword_fact`, which uses the same month arithmetic as the blueprint sampler. The numbers shown to the recruiter are always the computed ones. A company name does not count as evidence of a skill.
- **Hard and soft in one function (rule 5).** The screening step calls `apply_requirements` and takes "listable" from it. The ranking cannot add a candidate that function did not admit, whatever the model's score.
- **List sizes from one function (rule 6):** `list_sizes`, with whole-number arithmetic for the half-up rounding.

## Decisions and why

- **One run, two lists.** The short list is the top of the long list, so it is a subset by construction, not by a check afterwards.
- **The model is not handed the computed facts.** It reads the CV and says what it found; code then checks it. Handing it the facts would make the evidence check a formality, and the "evidence accuracy" figure in stage 8 meaningless.
- **Strengths and concerns name their keywords.** A strength lists the script keywords it rests on, a concern the ones the candidate lacks. That lets code check both without guessing at the meaning of a sentence: a strength built on a keyword that is not in the CV is removed, and so is a concern about a keyword that is there.
- **The reasoning paragraph is checked sentence by sentence.** A sentence is removed if it names a script keyword the CV does not contain, or states a number of years that matches nothing computed. This can also remove a harmless sentence such as "there is no Kubernetes experience". That loss is accepted: absences belong in the concerns, where they are structured.
- **The rationale opens with facts written by code** ("Found in the CV: Azure (6.8 years). Not found: Kubernetes."), followed by what is left of the model's reasoning.
- **Years within one year of the computed value are accepted.** Outside that, the computed value replaces the stated one and the difference is flagged.
- **Out-of-date inputs block a new run.** If the candidates or the script are out of date, the list actions are disabled and say which one to redo first. Stale inputs are not silently used.
- **Existing lists stay visible when they go out of date**, with a warning, until the recruiter generates them again (which asks for confirmation).
- **Regenerating candidates deletes the lists made from the old ones.** The PRD said "marks out of date". But those lists name people who no longer exist. The confirmation dialog for regenerating candidates now says that the lists are deleted too.
- **A failed run shows no half-finished list.** Assessments are stored one by one, so Retry only asks for the missing ones, but list membership is decided only when all of them are in.
- **Limits:** 10 screening runs per workspace, one job at a time.
- **The assessment model is still `mistral-small-2603`.** The PRD wants a stronger model here, chosen after a comparison. `mistral-medium-2604` has a price entry and can be switched on with one setting.

## What was seen in practice

- 689 backend tests pass, 86 frontend tests and 7 browser tests. Lint, types and the build are clean.
- **Tests that break the system on purpose, all passing:**
  - CVs that name their owner and give an email and phone number: none of it reaches the model input.
  - A model that claims a keyword no CV contains, inflates every number of years and adds an unsupported strength: all removed or corrected, each flagged, and nothing of it in the text the recruiter reads.
  - A model that gives every candidate 100: no candidate who misses a hard requirement gets on a list unflagged.
  - A script nobody can meet: the list is still filled, every entry carrying the flag "hard requirement not met".
- **With the fake model, which agrees with the facts, the planted strong matches fill the short list** for a pool of 20. This proves the pipeline, not the model.
- List sizes checked at 1, 2, 5, 10, 15, 20, 25 and 100 candidates, and the invariants for every size from 1 to 100.
- The whole flow was run in a browser test: candidates, script, long list, evidence view, short list. The long list and the evidence view were checked by eye.

## Still open

- **Nothing of this stage has run against the real model yet.** The open questions are real ones:
  - How often does a real model claim keywords or years the CV does not support? That is the evidence accuracy.
  - How well do the script's keywords match the wording of real CVs? The script and the candidate pool were extracted separately, so "CI/CD" in one may be "CI/CD pipelines" in the other, and whole-word matching will miss it.
  - Does the model's fit score add anything over the deterministic score, or mostly repeat it?
  - Small model or medium model for assessment: quality against a price about ten times higher.
- **The sentence check on the reasoning is blunt.** It works on keywords and numbers. A false statement that names neither passes.
- **Keyword matching is literal**: whole words, ignoring case. "Azure" in the script is found in "Microsoft Azure", but an abbreviation such as "MS Azure" for a script keyword "Microsoft Azure" is missed, and there are no synonyms. Real CVs would need more.
- **Evaluation** (precision, recall, consistency, the name-swap test) is stage 8. The counts of claims made and supported are already stored per assessment for it.
- **No CSV export.** Still an open decision.
