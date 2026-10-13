import httpx
import pytest

from app.main import create_app


@pytest.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_get_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_head_returns_ok(client: httpx.AsyncClient) -> None:
    """Uptime monitors send HEAD; a GET-only route would answer 405."""
    response = await client.head("/health")

    assert response.status_code == 200
    assert response.content == b""


async def test_unknown_route_is_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
