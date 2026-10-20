# Stage 9: Deployment and write-up

Date: 2026-10-14 to 2026-10-20

## What was built

- **One Docker image** (`Dockerfile`): the frontend is built with Node, then served by the FastAPI backend on the same origin. Pinned versions (Node 20.20.2, Python 3.12.13, uv 0.11.22), dependencies from the lock file, no development dependencies, runs as a user without root rights. `deploy/start.sh` runs the migrations, then uvicorn. CI builds the image on every push.
- **`APP_ENV=production`** makes the app refuse to start without a daily spend cap, secure cookies, the client IP header and (with the real model) an API key. The message names what is missing, nothing more.
- **The visitor's address** comes from one function (`app/web/client.py`), used by both per-IP limits. Behind Railway's proxy it reads `CLIENT_IP_HEADER` (`x-real-ip`); without that setting it uses the connection's address and ignores any header a visitor sends.
- **`scripts/check_deployment.py`** checks a deployment from outside: the health endpoint, the frontend, every API route answering 401 without a session (25 routes, listed from the code), and with `--spoofing`, that a made-up IP header does not get around the lockout.
- **`scripts/take_screenshots.py`** walks through the app in a browser and saves the README screenshots. It asks for the code without showing it and does not store it.
- **A runbook** in the README ("How to deploy"): trying the production image locally, set-up, variables, deploy, checks, codes for production, operations, and removing everything.
- **The write-up**: the README now opens for a reader who is not a developer: what the app does, how it is built and why, the safeguards with the test behind each, the measured results with what they do and do not show, cost per step, and honest limits.

## Decisions and why

- **No `railway.json`.** Railway's Config as Code is deprecated: new services no longer read it, and existing files stop working on 2026-12-01. Its replacement, Infrastructure as Code, is a TypeScript file applied with the CLI. For one service and a database, a few dashboard settings described in the runbook are simpler, and the image carries its own start command.
- **The address header is a setting, not a default.** Railway documents `X-Real-IP` as set by its edge, but forum threads contradict each other on whether visitors can spoof these headers. So the app trusts a header only when told to, and `check_deployment.py --spoofing` tests it on the live deployment. Run against the local container, where nothing overwrites the header, the check failed as it should: that is the evidence it can tell.
- **Production protections are checked at startup, outside the settings validation.** The first version used a Pydantic validator; its error message printed part of the raw input, which includes the secrets. Now all settings errors hide their input (`hide_input_in_errors`), and a test checks that a rejected pepper does not appear in the message.
- **No uvicorn access log.** It records visitors' IP addresses; the app logs its own events with ids and counts (CLAUDE.md rule 12).
- **Spend cap $1.00 a day in production**, and a monthly limit on the Mistral account. From the per-call costs measured in the stage 8 evaluation, a full session (one vacancy, 100 candidates, script, lists, questions) costs about 5 to 6 cents, so the cap allows about 15 to 20 such sessions a day.
- **Deploy on push, after CI**, one replica, never sleeping: a visitor from LinkedIn should not meet a cold start.

## What was seen in practice

- **The image runs.** Locally, in production mode with the fake model: migrations on start, health check, frontend, 401 without a session, a non-root user. The same image refused to start without `CLIENT_IP_HEADER`, and the message held no secret.
- **A stalled progress dialog.** The first screenshot run stopped at "0 of 10 candidates created" although the job had finished in 7 seconds. Polling (TanStack Query) skips its timer while the page does not count as focused, which a headless browser can report. The next two runs passed, so the cause is likely but not proven. Polling now continues in the background too; it only happens while a job runs.
- **The per-IP session limit stopped my own test runs** after five sessions in an hour, as designed.
- **Not deployed.** The author decided not to deploy for now (2026-10-20). Everything up to the deployment itself is in place and was tested locally; the README says so plainly.

## Still open

- **The deployment itself**: the Railway project, the live checks, the production codes and the screenshots. The README has no screenshots until then: screenshots from the fake model would show its placeholder text, and taking them with the real model costs money and was not asked for.
- **Whether Railway's `X-Real-IP` holds** on a live deployment, and whether two networks are told apart. `check_deployment.py --spoofing` and a phone on another network answer this; until then the per-IP limits are tested only locally.
- **A link preview** (Open Graph tags and an image) for sharing on LinkedIn needs the final domain.
- **Railway's Infrastructure as Code** could replace the dashboard settings later, if the deployment grows beyond one service and a database.
