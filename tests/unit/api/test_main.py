"""Unit and integration tests for `src.api.main`.

Tests `health` directly as a plain coroutine (no HTTP involved), then `create_app`'s wiring via
`fastapi.testclient.TestClient` -- an in-process ASGI test client, no real network socket, no
`uvicorn` process, matching this repository's own established "tests must not require... network
access" convention (see `tests/unit/pipeline/test_integration.py`'s own docstring). Also asserts
Phase 17's confirmed scope directly: exactly one route, `GET /health`, and no other method
registered on that path.
"""

from __future__ import annotations

import asyncio

import src.api.main as api_main
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------------------
# health() -- the plain coroutine, with no HTTP involved
# --------------------------------------------------------------------------------------


def test_health_is_an_async_function() -> None:
    """`health` must itself be a coroutine function -- `create_app` wires it into an async ASGI
    route as-is, with no sync/async bridge, unlike `cli.main`'s own `_run`/`main` split."""
    assert asyncio.iscoroutinefunction(api_main.health)


def test_health_returns_healthy_status() -> None:
    """Calling `health` directly returns a minimal mapping reporting the process as healthy."""
    result = asyncio.run(api_main.health())
    assert result == {"status": "healthy"}


# --------------------------------------------------------------------------------------
# create_app() -- route wiring, verified via an in-process ASGI test client
# --------------------------------------------------------------------------------------


def test_create_app_registers_exactly_one_route() -> None:
    """Phase 17's confirmed scope is exactly one operation: `GET /health`, and nothing else."""
    app = api_main.create_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert paths == {"/health"}


def test_get_health_returns_200_and_expected_body() -> None:
    """A real `GET /health` request, through the actual ASGI app, returns `200` with the
    liveness body -- exercising `create_app`'s wiring end-to-end, not just `health` in
    isolation."""
    client = TestClient(api_main.create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_post_health_is_not_allowed() -> None:
    """Only `GET` is registered for `/health` -- Phase 17 introduces no other method."""
    client = TestClient(api_main.create_app())

    response = client.post("/health")

    assert response.status_code == 405


def test_module_level_app_is_a_configured_fastapi_app() -> None:
    """The module-level `app` `uvicorn` serves is exactly what `create_app` returns -- no hidden
    module-level side effects (no container, no plugin registry; see this package's own
    `__init__.py`)."""
    client = TestClient(api_main.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
