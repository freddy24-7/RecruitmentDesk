# Stage 3: Review, edit, cancel, submit

Date: 2026-10-13

## What was built

- **Review and edit.** A draft opens with each section in an editable field. Lists are edited as one item per line. Saving makes a new version. The text as the model wrote it is kept apart.
- **Reset to generated**, after a confirmation that says the edits will be lost.
- **Cancel vacancy.** A confirmation dialog states what will be deleted. On confirmation the draft is deleted and the user is back at the start. A failed generation can be cancelled from its card in the same way.
- **Submit vacancy.** Unsaved edits are saved first. Required sections must have content, and the message names the ones that are empty.
- **Submitted vacancies.** The list with title, sector, seniority, work mode and submitted date, and the empty state "No vacancies have yet been submitted".
- **A submitted vacancy** shows its text and five actions. "Edit vacancy" opens the same editor. The four generate actions are visible but disabled, each with its reason.
- **The backend serves the built frontend**, so the app is one service on one origin.
- **Browser tests** with Playwright, also in CI.
- **Third migration** (`0003`): `vacancy.submitted_at`.

## Decisions and why

- **One deletion path** (`app/vacancy/deletion.py`). It takes a `confirmed` flag and refuses without it. The API requires `confirm=true`, which the UI sends only after its dialog. A test parses the source and fails if any other module deletes rows.
- **Two kinds of rows survive a cancel, on purpose.** Job rows stay, without a link to the vacancy, because they count towards the workspace limit: deleting a vacancy must not give the generation budget back. Usage records stay, because the cost was made. Neither holds any vacancy content, and a test searches every text and JSON column of every table to prove it.
- **A draft may be saved with empty sections; a submitted vacancy may not.** There are two schemas: a lenient one for drafts and a strict one for submitting and for model output. A submitted vacancy is used by later steps, so edits to it must keep it complete.
- **Cancel applies to drafts and failed generations only.** Not while a vacancy is being written (the running job would trip over the missing row), and not to submitted vacancies (the PRD puts Cancel on the draft review; "Reset demo" comes in stage 8).
- **The server decides which actions are available**, in one function, and sends them with the vacancy. The screen only renders them, so the two cannot disagree.
- **Disabled actions use `aria-disabled`, not `disabled`.** A truly disabled button cannot be reached with the keyboard, so a screen reader user would never hear the reason.
- **"Not available yet in this version of the demo"** is the honest reason for "Generate candidates" and "Generate selection script" until stages 4 and 5 build them. The two list actions already show their real prerequisite.
- **Versions are a counter, not a history.** The data model keeps the current text and the generated text. That is enough for "Reset to generated". Earlier edits cannot be brought back.
- **Flags follow the text.** The wording check runs again on every save.
- **New dependencies:** `@radix-ui/react-alert-dialog` (confirmation dialogs with the right role and focus handling) and `pytest-playwright` (browser tests).

## What was seen in practice

- 240 backend tests pass (unit and integration, 98% coverage), 35 frontend tests, and 4 browser tests. Lint, types and the build are clean.
- **The browser tests found a real bug that the other tests missed.** After a dialog closed, keyboard focus was dropped instead of going back to the button that opened it. Radix only returns focus by itself when the dialog is opened by its own trigger, and ours are opened from state. Fixed with a small hook, and now tested in both jsdom and the browser.
- **Tests that break the rules on purpose pass:** a second deletion path is caught (a `delete()` in another module, a `session.delete()`, and raw `DELETE FROM` in a string), while a route named `delete` and a docstring that mentions the words are not mistaken for one.
- The browser flow was run end to end against the real backend with the fake model: code entry, generate, spinner, review, edit, save, submit, open the submitted vacancy, reload. Screenshots of the dialog, the editor and the submitted view were checked by eye.
- The cookie is marked Secure and still works on `http://localhost` in Chromium, so the browser tests run with the production cookie settings.

- **The first CI run of the browser tests failed.** They assumed the test database already existed. On the development machine it did, because the integration tests had created it; in CI the browser tests run as a separate job on an empty server. Both suites now create the database through one shared helper, and both were re-run locally against a database name that did not exist yet.

## Still open

- **Still nothing has run against the real Mistral API.** The account is on the free plan, where API keys are not active. One real call is prepared (`uv run pytest -m mistral tests/real -s`).
- **Stale-data marking is not built yet**, because nothing can go stale yet. Editing a submitted vacancy raises its version; stages 4 to 6 will compare against that version to mark candidates, script and lists as out of date.
- **Status chips** on the submitted list ("20 candidates", "script ready") arrive with those stages.
- **Unsaved edits are lost without a warning** when the user leaves the editor with "Back". The editor does show "You have unsaved changes".
- **The browser tests use Chromium only.** Safari does not accept Secure cookies on `http://localhost`, which matters only for local development there.
- **The page has no client-side routes.** A reload returns to the start view, not to the vacancy that was open.
