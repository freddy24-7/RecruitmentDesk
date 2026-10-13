"""The backend serves the built frontend, without shadowing or exposing the API."""

from pathlib import Path

import httpx
import pytest

from app.config import get_settings
from app.main import create_app


@pytest.fixture
async def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>RecruitDesk</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log('app')")
    monkeypatch.setattr(get_settings(), "frontend_dist", str(tmp_path))
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="https://test")


async def test_the_page_and_its_files_are_served(served: httpx.AsyncClient) -> None:
    page = await served.get("/")
    script = await served.get("/assets/app.js")

    assert page.status_code == 200
    assert "RecruitDesk" in page.text
    assert script.status_code == 200


async def test_the_api_is_not_shadowed_and_still_needs_a_session(
    served: httpx.AsyncClient,
) -> None:
    assert (await served.get("/health")).json() == {"status": "ok"}
    for path in ("/api/session", "/api/vacancies", "/api/vacancy-options"):
        response = await served.get(path)
        assert response.status_code == 401
        assert response.json()["error"] == "no_session"


async def test_unknown_paths_are_not_found(served: httpx.AsyncClient) -> None:
    assert (await served.get("/api/does-not-exist")).status_code == 404
    assert (await served.get("/secrets.txt")).status_code == 404
    # No way out of the frontend folder.
    assert (await served.get("/../pyproject.toml")).status_code == 404
    assert (await served.get("/%2e%2e/pyproject.toml")).status_code == 404


async def test_without_a_built_frontend_the_api_still_works() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="https://test"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/")).status_code == 404
