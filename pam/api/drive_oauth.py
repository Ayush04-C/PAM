"""Local operator-only Drive provisioning; never exposed as MCP tools."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, StrictBool

from pam.api.google_oauth import InMemoryOAuthStateStore
from pam.integrations.drive_auth import DriveAuthorization, DriveAuthorizationError


class PermissionRequest(BaseModel):
    """Explicit transfer policy; reject unknown or coerced permissions."""

    model_config = ConfigDict(extra="forbid")
    allow_read: StrictBool
    allow_metadata_transfer: StrictBool
    allow_content_transfer: StrictBool = False
    confirmed_destination: str | None = None


def create_drive_oauth_router(
    authorization: DriveAuthorization,
    operator_secret: str,
    state_store: InMemoryOAuthStateStore | None = None,
) -> APIRouter:
    """Bind each one-time state to this fixed owner/account/client configuration."""
    states = state_store or InMemoryOAuthStateStore()
    lock = threading.RLock()
    redirect = urlsplit(authorization.config.redirect_uri)

    def local_request(request: Request, response: Response) -> None:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        if (
            request.client is None
            or request.client.host not in {"127.0.0.1", "::1"}
            or request.headers.get("host") != redirect.netloc
            or request.headers.get("origin", f"http://{redirect.netloc}")
            != f"http://{redirect.netloc}"
        ):
            raise HTTPException(403, "Drive provisioning is local only")

    def operator(request: Request) -> None:
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {operator_secret}"
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(401, "Operator authentication required")

    router = APIRouter(
        prefix="/oauth/google/drive", dependencies=[Depends(local_request)]
    )

    def safe(action: Callable[[], Any]) -> Any:
        try:
            with lock:
                return action()
        except DriveAuthorizationError as error:
            raise HTTPException(400, str(error)) from None
        except ValueError:
            raise HTTPException(
                400, "Drive authorization state or credentials are invalid"
            ) from None
        except Exception:
            raise HTTPException(
                503, "Drive authorization unavailable. Retry or reconnect."
            ) from None

    @router.post("/start", dependencies=[Depends(operator)])
    def start() -> dict[str, str]:
        def begin() -> dict[str, str]:
            verifier = secrets.token_urlsafe(64)
            state = states.create(verifier)
            return {
                "authorization_url": authorization.oauth.authorization_url(
                    state, verifier
                )
            }

        return dict(safe(begin))

    @router.get("/callback")
    def callback(request: Request) -> dict[str, str]:
        def complete() -> dict[str, str]:
            verifier = states.consume(request.query_params.get("state"))
            if verifier is None:
                raise DriveAuthorizationError(
                    "Invalid or expired Drive authorization state."
                )
            code = request.query_params.get("code")
            if request.query_params.get("error") or not code or len(code) > 4096:
                raise DriveAuthorizationError(
                    "Google authorization was denied or incomplete."
                )
            authorization.connect(code, verifier)
            return {"status": "connected", "model_transfer": "not authorized"}

        return dict(safe(complete))

    @router.get("/status", dependencies=[Depends(operator)])
    def status() -> dict[str, object]:
        def report() -> dict[str, object]:
            consent = authorization.consent(authorization.owner)
            return {
                "credential": "stored; live connectivity not checked",
                "allow_read": consent.allow_read,
                "allow_metadata_transfer": consent.allow_metadata_transfer,
                "allow_content_transfer": consent.allow_content_transfer,
                "model_destination": authorization.model_destination,
            }

        return dict(safe(report))

    @router.post("/check", dependencies=[Depends(operator)])
    def check() -> dict[str, str]:
        safe(authorization.check_connection)
        return {"status": "refresh and account verified"}

    @router.post("/permissions", dependencies=[Depends(operator)])
    async def permissions(request: Request) -> dict[str, str]:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4096:
                raise HTTPException(400, "Invalid permission request")
        try:
            values = PermissionRequest.model_validate_json(body)
        except ValueError:
            raise HTTPException(400, "Invalid permission request") from None
        await run_in_threadpool(
            safe, lambda: authorization.set_permissions(**values.model_dump())
        )
        return {
            "status": "permissions updated",
            "content_transfer": "enabled"
            if values.allow_content_transfer
            else "disabled",
        }

    @router.post("/disconnect", dependencies=[Depends(operator)])
    def disconnect() -> dict[str, str]:
        def forget() -> None:
            states.clear()
            authorization.disconnect()

        safe(forget)
        return {"status": "locally disconnected", "google_grant": "not revoked"}

    return router
