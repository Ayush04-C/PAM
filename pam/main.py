"""FastAPI application factory for PAM."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from pam.api.audit import AuditSink, InMemoryAuditSink
from pam.api.availability import create_availability_router
from pam.api.google_oauth import InMemoryOAuthStateStore, create_google_oauth_router
from pam.application import AvailabilityService
from pam.application.local_calendar import create_local_availability_service
from pam.config import Settings
from pam.integrations.google_calendar import GoogleOAuthClient
from pam.integrations.google_wiring import (
    create_google_availability_service,
    credential_store,
    google_oauth_config,
)
from pam.logging import configure_logging, request_id_context

REQUEST_ID_HEADER = "X-Request-ID"


def create_app(
    availability_service: AvailabilityService | None = None,
    audit_sink: AuditSink | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Create PAM's local HTTP application with explicit dependencies."""
    configure_logging()
    app = FastAPI(title="PAM", version="0.1.0")
    logger = logging.getLogger("pam.http")
    active_settings = settings or Settings()
    if availability_service is not None:
        service = availability_service
    elif active_settings.calendar_backend == "google":
        service = create_google_availability_service(active_settings)
    else:
        service = create_local_availability_service()
    recorder = audit_sink or InMemoryAuditSink()

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

    app.include_router(create_availability_router(service, recorder))
    oauth_client: GoogleOAuthClient | None = None
    oauth_store = None
    if active_settings.calendar_backend == "google":
        oauth_client = GoogleOAuthClient(google_oauth_config(active_settings))
        oauth_store = credential_store(active_settings)
    app.include_router(
        create_google_oauth_router(oauth_client, InMemoryOAuthStateStore(), oauth_store)
    )

    return app


app = create_app()
