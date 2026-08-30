"""`health` and `create_app`: the two plain functions that make up this layer's entire public
contract for Phase 17.

`health` answers exactly one question -- is this process itself up and able to answer a request
-- and answers it unconditionally: reaching this function's body at all *is* the liveness signal,
so it calls nothing else, checks no inner-layer dependency, and cannot raise. This deliberately
mirrors `cli.main`'s own "this layer's contract is this thin on purpose" precedent
(`src.application.runner`'s own module docstring makes the same point for `build_pipeline`/
`run_flow`): a readiness check that verifies a configured storage or vector backend is reachable
would need to construct a concrete Port (via `src.bootstrap.wiring.build_storage`/
`build_vector_store`) and is a genuinely different, larger contract that Phase 17's confirmed
scope does not include.

`create_app` assembles the ASGI application `uvicorn` serves, registering `health` at `GET
/health` and nothing else. See this package's own `__init__.py` for why no other `src.*` import
appears anywhere in this module.
"""

from __future__ import annotations

from fastapi import FastAPI

#: HTTP path this layer's one Phase 17 operation is registered under.
_HEALTH_PATH = "/health"


async def health() -> dict[str, str]:
    """Report this process's own liveness.

    Reaching this function's body at all is the liveness signal itself -- it calls nothing else
    and cannot raise. See this module's own docstring for why a readiness check (verifying a
    configured backend is actually reachable) is a different, larger contract Phase 17's
    confirmed scope does not include.

    Returns:
        A minimal mapping reporting the process as healthy.
    """
    return {"status": "healthy"}


def create_app() -> FastAPI:
    """Construct the API layer's ASGI application.

    Registers `health` at `GET /health` -- Phase 17's one confirmed operation -- and nothing
    else. Builds a plain `FastAPI` instance directly; no dependency-injection container, plugin
    registry, or `infrastructure` package is constructed or referenced. See this package's own
    `__init__.py` for why.

    Returns:
        A fully configured `FastAPI` application, ready for `uvicorn` to serve.
    """
    # `docs_url`/`redoc_url`/`openapi_url` are FastAPI's own auto-registered interactive-docs
    # routes, on by default. Phase 17's confirmed scope is exactly one endpoint, `GET /health`;
    # disabling these keeps that true literally, not just for hand-written routes.
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_api_route(_HEALTH_PATH, health, methods=["GET"])
    return app


#: The ASGI application `uvicorn` serves, e.g. `uvicorn src.api.main:app`.
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
