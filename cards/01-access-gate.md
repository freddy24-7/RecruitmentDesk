# Stage 1: Access gate

Date: 2026-10-13

## What was built

- **Code entry screen.** Without a session the frontend shows only this screen. On every page load it first asks the server whether a session exists, so a reload never asks for the code again.
- **Redeeming a code** (`POST /api/session`). A valid code creates a workspace and sets a signed session cookie (HttpOnly, Secure, SameSite=Lax).
- **Session guard.** Every route except the code entry endpoint and the health check sits under one router that requires a valid session and otherwise answers 401.
- **Brute-force limits** in `app/limits/attempts.py`: 10 failures per IP per 15 minutes, and 100 failures per hour for everyone together.
- **`scripts/manage_codes.py`** with `create`, `status`, `extend` and `disable`.
- **First migration** (`0001`): tables `access_code`, `failed_attempt` and `workspace`.
- **Structured JSON logs** with `structlog`.

## Decisions and why

- **Atomic counting with one conditional `UPDATE`** (`uses < max_uses`, with `RETURNING`). PostgreSQL locks the row, so simultaneous requests are counted one after another. A check constraint (`uses <= max_uses`) is a second line of defence.
- **Codes are stored as HMAC-SHA256 hashes with a pepper.** A plain hash would be useless here: there are only about 8 million possible codes, so anyone with the database could try them all in seconds. With the pepper they also need the environment variable.
- **The pepper and the session secret are separate, required, and at least 32 characters.** The app does not start without them. Separate, so that ending all sessions does not invalidate the codes.
- **One "use" is one new session.** Entering a code while a session is still valid returns the existing session and costs nothing.
- **A disabled code is reported as "not valid".** Only a used-up code gets its own message, as specified.
- **A used-up code also counts as a failed attempt**, so the "used up" message cannot be used to probe for codes without limit.
- **During a lockout the code is not checked at all.** Valid, used-up and unknown codes get the same answer, so the lockout reveals nothing.
- **IP addresses are stored as keyed hashes**, because an IP address is personal data.
- **The code travels in the request body, never in the URL**, so it cannot appear in access logs.
- **Messages are written on the server only.** The frontend shows what the server sends, so the wording lives in one place.
- **Interactive API docs and the OpenAPI URL are switched off**, because they would be reachable without a session.
- **Tests run on their own database** (`<name>_test`), created automatically, so they never touch development data.
- **New dependencies:** `itsdangerous` (signing the cookie), `structlog` (logs), and `hatchling` as build backend so `scripts/` can import `app`.

## What was seen in practice

- 105 backend tests and 9 frontend tests pass locally. Backend coverage is 97%.
- **25 simultaneous redemptions of a code with one use left gave exactly one success and 24 "used up" answers**, with the counter at 20 and one workspace created.
- The route check walks every route of the app. It was also run against an app with a deliberately unprotected route, and caught it.
- The log test captures everything, including the SQL statements and their parameters, and finds no submitted code. Only hashes and the code label appear.
- A live run (backend plus the Vite dev server, with a throwaway code in the test database) behaved as specified: 401 without a session, the "not valid" message, a lowercase space-padded code accepted, no extra use on reload, and the "used up" message with the contact link on the third visitor of a two-use code.
- **Two surprises worth remembering:**
  - Alembic's default logging setup switches off all existing loggers. After migrations had run in the same process, the application logged nothing. Fixed in `migrations/env.py`. The log test caught this.
  - Coverage reported lines after a database call as not covered, until it was told that SQLAlchemy's async engine uses greenlets.
- The stage 0 open item is closed: the CI workflow ran green on GitHub for the skeleton commit.

## Still open

- **Client IP behind the host's proxy.** The per-IP limit uses the address the server sees. Behind Railway that depends on proxy headers, which a client may be able to forge. The global ceiling still holds in that case. To be checked on the real host in stage 9.
- **The global ceiling can be triggered on purpose.** 100 failed attempts in an hour block code entry for everyone for up to an hour. Existing sessions keep working. Accepted for a demo.
- **The per-IP limit is not exact under simultaneous requests**: a burst can get a few attempts past 10 before the lockout starts. The redemption limit, in contrast, is exact.
- **Old rows are not removed yet.** Failed attempts and expired workspaces stay in the database until the clean-up in stage 8.
- **The gate has not been tried in a real browser.** The first browser tests (Playwright) come in stage 3.
- No real access codes exist yet. Creating them is a step for the developer (see the README).
