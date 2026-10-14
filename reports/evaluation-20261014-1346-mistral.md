# Evaluation report (mistral)

Started 2026-10-14T13:37:11+00:00. Services: **mistral** (real Mistral API).
Models: vacancy mistral-small-2603, profile mistral-medium-2604, cv mistral-small-2603, script mistral-medium-2604, assessment mistral-small-2603, interview mistral-small-2603. Blueprint seed 20261013.

## Summary

| Vacancy | Candidates | Short-list precision | Long-list recall | Unflagged hard misses | Flagged entries | Evidence accuracy | Long-list overlap | Name swap: identical input / max score difference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Cloud Engineer (IT and software) | 20 | 1.00 | 1.00 | 0 | 6 of 6 | 0.46 (77/168) | 1.00 | 2/2 / 0 |
| Financial Controller (Finance) | 18 | 1.00 | 1.00 | 0 | 1 of 5 | 0.69 (104/151) | 1.00 | 2/2 / 0 |
| District Nurse (Healthcare) | 19 | 1.00 | 1.00 | 0 | 6 of 6 | 0.71 (92/130) | 1.00 | 2/2 / 0 |
| Supply Chain Planner (Logistics) | 18 | 1.00 | 1.00 | 0 | 3 of 5 | 0.73 (99/135) | 1.00 | 2/2 / 0 |

## Facts only, model only, combined

Short-list precision and long-list recall when the final ranking uses only the scores computed by code, only the model's fit score, or both (the setting in use).

| Vacancy | Facts only | Model only | Combined |
| --- | --- | --- | --- |
| Cloud Engineer | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| Financial Controller | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| District Nurse | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| Supply Chain Planner | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |

## Interview questions

From the short list of the last screening run. A dropped question named a source that was not offered; a flagged one may touch a protected attribute and needs review.

| Vacancy | Question sets | Questions | Dropped | Flagged | Reference codes in the text |
| --- | --- | --- | --- | --- | --- |
| Cloud Engineer | 3 | 17 | 0 | 0 | 0 |
| Financial Controller | 3 | 18 | 0 | 0 | 0 |
| District Nurse | 3 | 17 | 0 | 0 | 0 |
| Supply Chain Planner | 3 | 18 | 0 | 0 | 0 |

## Per vacancy

### Cloud Engineer (IT and software)

- Planted categories: {'adjacent': 6, 'partial': 7, 'strong': 3, 'weak': 4}. List sizes: long 6, short 2.
- Long list (planted categories, in order): strong, strong, strong, partial, partial, partial.
- Short list: strong, strong.
- Short-list overlap over repeated runs: [1.0, 1.0]; long list: [1.0, 1.0].
- Vacancy rubric: all_sections_filled yes, no_flagged_wording yes, title_matches yes, work_mode_mentioned yes, seniority_mentioned yes.
- Script as proposed: hard: AWS | Azure | GCP (5y); hard: EC2 | S3 | Lambda | VPC (5y); hard: Terraform | CloudFormation | Pulumi (3y); hard: Docker | Kubernetes (2y); hard: Python | Bash | PowerShell (0y); hard: ISO 27001 | SOC 2 (0y); hard: Prometheus | Grafana | ELK Stack | Azure Monitor (0y); soft: AWS Certified Solutions Architect – Professional | Microsoft Certified: Azure Solutions Architect Expert | Google Professional Cloud Architect (0y); soft: AWS Lambda | Azure Functions (0y); soft: Istio | Linkerd (0y).

### Financial Controller (Finance)

- Planted categories: {'adjacent': 5, 'partial': 7, 'strong': 3, 'weak': 3}. List sizes: long 5, short 2.
- Long list (planted categories, in order): strong, strong, strong, partial, partial.
- Short list: strong, strong.
- Short-list overlap over repeated runs: [1.0, 1.0]; long list: [1.0, 1.0].
- Vacancy rubric: all_sections_filled yes, no_flagged_wording yes, title_matches yes, work_mode_mentioned yes, seniority_mentioned NO.
- Script as proposed: soft: Dutch GAAP | IFRS (0y); hard: SAP | Oracle | Microsoft Dynamics (0y); hard: Excel (0y); hard: Dutch | EU financial regulations | tax laws (0y); hard: English (0y); soft: Dutch (0y); soft: RA | CPA (0y); soft: Power BI | Tableau (0y); soft: FinTech | SaaS (0y).
- Problems during the run: candidates: llm_timeout.

### District Nurse (Healthcare)

- Planted categories: {'adjacent': 6, 'partial': 7, 'strong': 2, 'weak': 4}. List sizes: long 6, short 2.
- Long list (planted categories, in order): strong, strong, partial, partial, partial, partial.
- Short list: strong, strong.
- Short-list overlap over repeated runs: [1.0, 1.0]; long list: [1.0, 1.0].
- Vacancy rubric: all_sections_filled yes, no_flagged_wording yes, title_matches yes, work_mode_mentioned yes, seniority_mentioned NO.
- Script as proposed: hard: BIG-registratie (0y); hard: community nursing | district nursing (3y); hard: electronic health record systems | nursing documentation software (0y); hard: Dutch (0y); hard: English (0y); hard: Dutch healthcare regulations | Dutch healthcare standards (0y); soft: geriatric care | palliative care (0y); soft: IV therapy | diabetes management (0y); soft: Dutch healthcare insurance systems | reimbursement processes (0y).
- Problems during the run: candidates: llm_invalid_output.

### Supply Chain Planner (Logistics)

- Planted categories: {'adjacent': 5, 'partial': 7, 'strong': 2, 'weak': 4}. List sizes: long 5, short 2.
- Long list (planted categories, in order): strong, strong, partial, partial, partial.
- Short list: strong, strong.
- Short-list overlap over repeated runs: [1.0, 1.0]; long list: [1.0, 1.0].
- Vacancy rubric: all_sections_filled yes, no_flagged_wording yes, title_matches yes, work_mode_mentioned yes, seniority_mentioned yes.
- Script as proposed: hard: SAP IBP | Oracle SCM | Kinaxis RapidResponse (0y); hard: Excel | SQL | Python (0y); soft: CSCP | CPIM | APICS (0y); hard: English (0y); hard: Agile (0y); soft: APS (0y); hard: ERP (0y); soft: Lean manufacturing | Six Sigma (0y); soft: AI-driven demand planning tools (0y); hard: Supply Chain Management | Logistics | Industrial Engineering (0y).
- Problems during the run: candidates: llm_timeout.

## Cost and latency

From the usage records of this run. Estimated cost in US dollars.

| Call | Calls | Invalid answers | Estimated cost | Average latency |
| --- | --- | --- | --- | --- |
| assessment | 132 | 0 | $0.07060 | 3729 ms |
| cv | 84 | 9 | $0.02624 | 3466 ms |
| evaluation_name_swap | 16 | 0 | $0.00879 | 3667 ms |
| interview | 12 | 0 | $0.00498 | 3116 ms |
| script | 4 | 0 | $0.02111 | 2834 ms |
| vacancy | 4 | 0 | $0.00195 | 8674 ms |
| vacancy_profile | 4 | 0 | $0.02230 | 3532 ms |

Total estimated cost: $0.1560.

## How to read this

- **Short-list precision**: the share of the short list that are planted strong matches.
- **Long-list recall**: the share of the planted strong matches that reached the long list. With more strong matches than places on the long list, 1.0 is not reachable.
- **Unflagged hard misses** must be 0: nobody may be listed with a missed hard requirement unless it is flagged.
- **Evidence accuracy**: the share of the model's claims about keywords and years that the CV supports. The rest was removed or corrected before anyone saw it.
- **Name swap**: the same CV with the candidate's name written into it, assessed under two different names. Blind screening should make the model's input identical; a score difference is then the model's own variation.
- **Interview questions**: the links and flags are checked in code; whether a question is good is not. The name swap is not run for follow-up questions: they are written from the same anonymised CV as the assessment.
- The candidates are synthetic and easier than real CVs: a CV never names a skill its owner lacks. These figures are an upper bound.
