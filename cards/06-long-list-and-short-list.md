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

## The real comparison (2026-10-14)

One real vacancy (senior cloud engineer), 20 real candidates (3 strong, 7 partial, 6 adjacent, 4 weak), a real script proposal saved unedited, then screening. Measured from the usage records and the assessments. Total real spend: about $0.11.

**Small against medium model, same pool, same script (prompts version 1):**

| | `mistral-small-2603` | `mistral-medium-2604` |
| --- | --- | --- |
| Assessments | 12, all usable on the first answer | 12, all usable on the first answer |
| Estimated cost | $0.0064 | $0.0628 (about 10 times) |
| Average latency | 3.2 s | 2.7 s |
| Short list | 2 of 2 planted strong matches | 2 of 2 planted strong matches |
| Long list | the 3 strong matches, then 3 partial | the same 6 candidates |
| Claims that held | 72 of 103 (70%) | 75 of 100 (75%) |
| Keywords claimed that are not in the CV | 9 | 0 |
| Years corrected | 22 | 25 |

- **The lists were the same.** All three planted strong matches reached the long list with both models, and the short list held only strong matches. The scores differed (the medium model was stricter with partial matches) but not the outcome.
- **The medium model invented no keywords; the small model invented nine**, all for adjacent candidates. The evidence check caught every one of them.
- **Both models got years wrong often**, usually too low: for example "4 years of Terraform" where the dated jobs give 6.3. The check corrected them in the claims.
- **One pool, one vacancy.** The figures show what can happen, not rates.

**What the comparison exposed, and what was changed:**

1. **Years in the strengths were not checked.** The strengths shown to the recruiter repeated the model's wrong years. Now every number of years in a strength, concern or reasoning sentence is compared with the computed values (also when written as words, "twelve years"), and a point that states wrong years is removed and flagged.
2. **The reasoning lost its main sentences**, because they named missing keywords or years. The assessment prompt (now version 2) asks the model to leave years and keyword lists out of its text, because code shows those above it, and to write about relevance, progression and responsibility instead.
3. **The script prompt split alternatives.** The vacancy said "AWS and/or Azure" and "compliance frameworks (e.g., ISO 27001, SOC 2)"; version 1 of the script prompt made separate hard items of each, which no planted candidate could meet together. Version 2 treats "and/or", "e.g." and examples in brackets as alternatives, and prefers one item with alternatives when in doubt.
4. **Claims named whole criteria lines** ("AWS or Azure or Google Cloud") as if they were one keyword, after the change above: 80 claims were rejected for that alone. The criteria are now listed to the model one keyword at a time, and the prompt asks for one keyword per claim.

**Fresh pool with the revised prompts, small model** (new vacancy and candidates, because the test suite had emptied the test database in between):

- The script now grouped the alternatives as the vacancy meant them: `AWS | Azure | Google Cloud`, `Terraform | CloudFormation | Pulumi`, `Docker | Kubernetes`, `Prometheus | Grafana | Azure Monitor`.
- Short list: 2 of 2 strong matches. Long list: the 3 strong matches, then 3 partial.
- 20 of 20 CVs (two were retried once). 12 assessments, $0.0073.
- Claims that held: 102 of 163 (63%). The 33 keywords claimed but not in the CV were real inventions ("CI/CD pipelines", "ISO 27001"), all caught. 28 years were corrected.
- The strengths no longer state years. The reasoning kept its main sentences.

**Still wrong, and not fixed:** every listed candidate in both pools carried "hard requirement not met". The script proposal adds requirements the candidate pool was never planted with (in the second pool "CI/CD pipelines" and "ISO 27001 | SOC 2", taken from the responsibilities). The vacancy profile (which plants the pool) and the script proposal (which screens it) are extracted separately, on purpose, and they disagree. The lists still come out right, because the ranking falls back to "fewest missed requirements first", but every entry is flagged. A recruiter who reviews the script would make those items soft. A decision is needed before the evaluation in stage 8 (see "Still open").

**Choice of model:** the assessment stays on `mistral-small-2603`. The medium model produced the same lists at ten times the price; its one advantage, fewer invented keywords, is covered by the evidence check.

## Still open

- **The script and the candidate pool disagree** (see above). Decided with the author: option B. A proposed item can only be hard if its quote comes from the required qualifications; code finds the section of each quote and turns anything else into a soft item, with a note in the dialog that says so. The recruiter can still make any item hard. Implemented and tested with the fake model; not yet re-run against the real model.
- **Near-misses in wording**: the profile planted "subnets", the script asked for "subnet". Whole-word matching misses that.
- **Does the model's fit score add anything over the computed score?** In both pools it agreed with it on the order of the top six. Two pools cannot show more.
- **Evidence accuracy of 63 to 75% means a quarter to a third of the model's claims were wrong.** The check removes them, so the recruiter does not see them, but it shows how much the check is needed.
- **The sentence check on the reasoning is blunt.** It works on keywords and numbers. A false statement that names neither passes.
- **Keyword matching is literal**: whole words, ignoring case. "Azure" in the script is found in "Microsoft Azure", but an abbreviation such as "MS Azure" for a script keyword "Microsoft Azure" is missed, and there are no synonyms. Real CVs would need more.
- **Evaluation** (precision, recall, consistency, the name-swap test) is stage 8. The counts of claims made and supported are already stored per assessment for it.
- **No CSV export.** Still an open decision.
