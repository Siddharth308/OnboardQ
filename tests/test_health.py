from httpx import AsyncClient


async def test_healthz_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_returns_ready(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_response_carries_generated_request_id(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    request_id = response.headers.get("x-request-id")
    assert request_id is not None
    assert len(request_id) == 36  # uuid4 string form
