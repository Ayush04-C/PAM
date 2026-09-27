"""FastAPI application factory for PAM."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from pam.logging import configure_logging, request_id_context

REQUEST_ID_HEADER = "X-Request-ID"


def create_app() -> FastAPI:
    """Create the minimal, dependency-free PAM HTTP application."""
    configure_logging()
    app = FastAPI(title="PAM", version="0.1.0")
    logger = logging.getLogger("pam.http")

    @app.middleware("http")
    async def add_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "request completed", extra={"status_code": response.status_code}
            )
            return response
        finally:
            request_id_context.reset(token)

    @app.get("/health")
    async def health() -> JSONResponse:
        """Provide a deterministic local liveness response."""
        return JSONResponse({"status": "ok"})

    return app


app = create_app()
