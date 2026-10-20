"""Check a running deployment from the outside (PRD section 11).

    uv run python scripts/check_deployment.py https://<your-app>.up.railway.app
    uv run python scripts/check_deployment.py <url> --spoofing

Always checked: the health endpoint, the frontend, and that every API route
except the public ones answers 401 without a session. The routes are listed
from the local code, so deploy first and check the same commit.

With --spoofing: sends failed code entries, each with a different made-up
address in X-Real-IP and X-Forwarded-For. If the host passes the visitor's
real address, the lockout still starts after FAILED_ATTEMPTS_PER_IP failures.
If it does not, a visitor could get around the per-IP limits. The entries are
malformed codes, so no access code is involved or used up. Side effect: your
own address is locked out of the code screen for the lockout window.
"""

import argparse
import asyncio
import os
import re
import sys

import httpx

# Building the app here only lists its routes: no database, no model. Fake
# values, so the check needs no secrets and never reads them from .env.
os.environ |= {
    "APP_ENV": "development",
    "LLM_PROVIDER": "fake",
    "ACCESS_CODE_PEPPER": "check-deployment-not-a-real-pepper-0000",
    "SESSION_SECRET": "check-deployment-not-a-real-secret-0000",
}

from fastapi.routing import iter_route_contexts  # noqa: E402

from app.main import create_app  # noqa: E402

PUBLIC = {("GET", "/health"), ("HEAD", "/health"), ("POST", "/api/session")}
# Digits are never part of a code, so this is always rejected as malformed.
NOT_A_CODE = "00000"


def protected_routes() -> list[tuple[str, str]]:
    routes = []
    for route in iter_route_contexts(create_app().routes):
        if route.path is None or not route.path.startswith("/api"):
            continue
        for method in sorted(route.methods or set()):
            if (method, route.path) not in PUBLIC:
                routes.append((method, route.path))
    return routes


async def check(url: str, spoofing: bool, attempts: int) -> list[str]:
    problems: list[str] = []
    async with httpx.AsyncClient(base_url=url, timeout=30) as client:
        health = await client.get("/health")
        if health.status_code != 200:
            problems.append(f"/health answered {health.status_code}")

        page = await client.get("/")
        if page.status_code != 200 or "text/html" not in page.headers.get(
            "content-type", ""
        ):
            problems.append(f"/ did not serve the frontend ({page.status_code})")

        routes = protected_routes()
        for method, path in routes:
            response = await client.request(
                method, re.sub(r"\{[^}]+\}", "1", path), json={}
            )
            if response.status_code != 401:
                problems.append(
                    f"{method} {path} answered {response.status_code} without a session"
                )
        print(f"Checked {len(routes)} protected routes without a session.")

        if spoofing:
            for n in range(attempts + 1):
                response = await client.post(
                    "/api/session",
                    json={"code": NOT_A_CODE},
                    headers={
                        "X-Real-IP": f"198.51.100.{n + 1}",
                        "X-Forwarded-For": f"198.51.100.{n + 1}",
                    },
                )
                if response.status_code == 429:
                    print(f"Locked out after {n} failures with made-up addresses.")
                    break
            else:
                problems.append(
                    "no lockout: a visitor can choose their address by sending a "
                    "header, so the per-IP limits do not hold"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "url", help="the deployment, for example https://x.up.railway.app"
    )
    parser.add_argument(
        "--spoofing", action="store_true", help="also test the IP header"
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=10,
        help="FAILED_ATTEMPTS_PER_IP of the deployment",
    )
    args = parser.parse_args()

    problems = asyncio.run(check(args.url.rstrip("/"), args.spoofing, args.attempts))
    for problem in problems:
        print(f"FAIL: {problem}")
    print("All checks passed." if not problems else f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
