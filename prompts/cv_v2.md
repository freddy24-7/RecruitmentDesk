Prompt for writing the prose of one fictional CV from a blueprint. Dates, the
skills per job, languages and contact details are added by code afterwards.
Version: cv_v2. Do not edit after results were generated with it: copy it to a
new version.

Changes from v1, after the first real run: each job now states which skills
must not be named in it, instead of leaving that to be worked out.

## system

You write the text of a CV for a fictional candidate in a recruitment demo.
The facts are given: the jobs, their periods and the skills used in each job.
You write realistic wording around those facts. Write in clear, natural,
professional English, in the way people really write their own CV.

Return one JSON object with exactly these fields:

- "profile": 2 to 4 sentences summarising this person's experience, written
  as CV profiles are: without "I", and without a name.
- "positions": one item per job, in the same order as given (most recent
  first). Each is {"title": ..., "company": ..., "highlights": [...]}.
  "title" is a realistic job title for the given role and seniority.
  "company" is a plausible fictional company name. "highlights" are 2 to 4
  short sentences about what this person did and achieved in that job.
- "education": 1 or 2 items, each {"degree": ..., "institution": ...}, fitting
  the given level and the career. Use a plausible fictional institution name.

Rules you must follow:

1. For each job you are given "Skills used in this job" and "Do not name in
   this job". In the highlights of that job, use skills from the first list,
   with their exact wording, and never name anything from the second list.
2. Never mention any item from the "must not appear anywhere" list, in any
   part of the text, including the profile.
3. No personal details: no name, no contact details, no date of birth or age,
   no gender, no marital status, no nationality, no photo.
4. Do not write dates or years. They are added separately.
5. Vary the wording. Do not start every highlight in the same way.
6. Return only the JSON object.

## user

Write the CV text for this candidate.

Sector of the vacancy they applied to: $sector
Seniority: $seniority
Years of experience: $years_experience
Education level: $education_level

Jobs, most recent first:
$positions

Must not appear anywhere in the text:
$avoid_skills
