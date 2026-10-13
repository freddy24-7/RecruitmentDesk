# Stage 5: Selection script

Date: 2026-10-13

## What was built

- **Proposal from the model.** "Generate selection script" starts a background job that reads the vacancy and proposes items. Each item has keywords, a number of years, hard or soft, and the sentence from the vacancy it is based on.
- **The dialog.** The recruiter edits keywords and years, flips hard and soft, removes items and adds new ones. Cancel saves nothing. Submit saves the script.
- **Alternatives.** An item holds one to four keywords. Any one of them meets it: "AWS / Azure / GCP, 5 years".
- **Hard and soft logic in one function** (`app/script/requirements.py`), ready for the lists in stage 6.
- **Out of date.** Editing the vacancy marks the saved script as out of date, on the list, on the vacancy and in the dialog.
- **Fifth migration** (`0005`): the `selection_script` table and `job.result`.

## Decisions and why

- **Alternatives in one item**, agreed with the author before the stage. Real vacancies are written with "or". With one keyword per item, a hard requirement "AWS" would drop every Azure engineer the vacancy accepts. It also keeps the script in line with the candidate pool, which is planted with the same idea.
- **Years are not added up across alternatives.** Three years of AWS and three of Azure are not six years of one of them. The best single alternative counts. Easier to explain, and easier to verify against a CV. The dialog says so.
- **The proposal is its own model call on the vacancy text.** It does not reuse the vacancy profile from stage 4, although the two overlap. The profile is what the candidates were planted from. A script derived from it would make the evaluation circular.
- **The reason is checked by code.** The model is asked to quote the vacancy. Code looks the quote up in the vacancy text (ignoring case and spacing) and marks the item as grounded or not. An ungrounded reason is kept and shown as "not found in the vacancy text". The browser cannot set this flag: the server decides it again on every save.
- **A proposal is not a script.** It is stored with its job. Nothing becomes the vacancy's script until Submit. A waiting proposal is reused when the dialog is opened again, so the model is not paid twice for the same text.
- **Saving is the deliberate action that brings an out-of-date script up to date.** The script records the vacancy version it was saved for.
- **Too few candidates meet the hard requirements:** the best of the others become listable too, each carrying the requirements they miss. Nobody is listed with a missed hard requirement and no flag. A test checks that for every list size.
- **Score:** a hard item counts double. A keyword that is there for too few years earns part of the item, up to half. Documented in the module; the weighting with the model's assessment comes in stage 6.
- **One job of each kind is reported with the vacancy**, so a script proposal does not hide a failed candidate run and its Retry button.
- **Plain types in the model's schema** (`hard` as true or false, not a list of allowed words), as before, so a strict JSON mode has nothing to refuse.
- **Limit:** 20 proposals per workspace. Editing and saving by hand stays possible after that.

## What was seen in practice

- 515 backend tests pass, 72 frontend tests and 6 browser tests. Lint, types and the build are clean.
- **A test that breaks the rule on purpose:** no module other than `requirements.py` may compare an item's kind with hard or soft. The check parses the source.
- **A bug found by a frontend test:** when the request for a proposal was refused (for example at the limit), the dialog showed "no proposal yet" without the reason. The page and the dialog each held their own copy of the request. They now share one.
- **Real model calls (2026-10-13, `mistral-small-2603`):** six script proposals, each on a freshly generated vacancy, three for a cloud engineer and three for a district nurse. Measured from the usage records:
  - About 1,000 tokens in and 600 to 660 out per proposal, 2.4 to 2.9 seconds, **estimated $0.0005 each**.
  - **Every reason in all six proposals was an exact quote from the vacancy.** The grounding check found none to reject.
  - **Hard and soft followed the vacancy's sections:** required qualifications became hard, nice-to-haves soft.
- **The grouping of alternatives is the weak point**, and the prompt was changed twice because of it:
  - First version: grouped well for the cloud engineer, but put "Dutch | English" in one item for the nurse, where the vacancy needs both.
  - A rule "things asked together are separate items" overcorrected: it split "Python, Bash or PowerShell" into three hard requirements, so a candidate would need all three.
  - Final version: let the vacancy's wording decide ("or", "such as", "e.g." mean alternatives; "and" means separate items). The cloud engineer came out well: `AWS | Azure | GCP`, `Terraform | Pulumi | AWS CloudFormation`, `Python | Bash | PowerShell`. The nurse still got "Dutch | English" in one item.
  - Each run used a new vacancy text, so these runs do not compare like with like. They show a tendency, not a rate.
- **Sectors without named tools give vaguer keywords.** For the nurse: "health assessments", "quality improvement projects", "driver's license". These are fair summaries of the vacancy but poor search terms for a CV.
- **Some items come from the responsibilities, marked hard** (for example "ISO 27001 | SOC 2"), although the vacancy did not list them as required.
- Estimated real spend for this stage: about $0.006.

## Still open

- **The proposal needs the recruiter's review, and the UI says so.** Grouping mistakes and vague keywords are exactly what the dialog is for. But a recruiter who submits without reading gets a script with those flaws.
- **No measurement of proposal quality yet.** Six proposals read by eye is not an evaluation. A rubric (keywords present in the vacancy, sensible grouping) could be added in stage 8.
- **The script's keywords and the planted skills are extracted separately**, on purpose. They will not always use the same words ("AWS Certified Solutions Architect – Professional" in the script, a shorter name in the pool). Stage 6 will show how much that costs in matching.
- **A keyword that is a language** ("English") is matched like any other. Whether that works depends on how the CV names it.
- **The lists do not exist yet.** With candidates and a script both present, the two list actions say "Not available yet in this version of the demo".
