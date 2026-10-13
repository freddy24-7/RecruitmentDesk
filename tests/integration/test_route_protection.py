"""Nothing is reachable without a session (CLAUDE.md rule 14).

The check walks every route of the application, so a route added later is
covered without anyone remembering to write a test for it. It is also run
against an application that breaks the rule on purpose.
"""

import re

import httpx
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts

from app.main import create_app

# The complete list of routes that work without a session.
PUBLIC = {
    ("GET", "/health"),
    ("HEAD", "/health"),
    ("POST", "/api/session"),
}


async def reachable_without_session(app: FastAPI) -> set[tuple[str, str]]:
    """Request every route without a cookie; return those that do not answer 401."""
    reachable = set()
    checked = 0
    transport = httpx.ASGITransport(app=app, client=("203.0.113.50", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="https://test"
    ) as client:
        # iter_route_contexts also walks the routes of included routers.
        for route in iter_route_contexts(app.routes):
            assert route.path is not None, f"route without a path: {route!r}"
            path = re.sub(r"\{[^}]+\}", "1", route.path)
            for method in route.methods or set():
                response = await client.request(method, path, json={})
                checked += 1
                if response.status_code != 401:
                    reachable.add((method, route.path))
    # Guard against a check that silently finds no routes at all.
    assert checked >= len(PUBLIC) + 1
    return reachable


async def test_every_route_except_the_public_ones_requires_a_session() -> None:
    reachable = await reachable_without_session(create_app())

    assert reachable <= PUBLIC, f"reachable without a session: {reachable - PUBLIC}"


async def test_the_check_catches_a_route_added_outside_the_guard() -> None:
    app = create_app()

    @app.get("/api/leak")
    async def leak() -> dict[str, str]:
        return {"data": "should have been protected"}

    reachable = await reachable_without_session(app)

    assert ("GET", "/api/leak") in reachable


async def test_docs_and_schema_are_not_served() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="https://test"
    ) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404
