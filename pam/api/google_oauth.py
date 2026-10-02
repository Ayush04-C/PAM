"""Local-only Google OAuth HTTP routes with one-time state validation."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from pam.integrations.google_calendar import GoogleOAuthClient, GoogleReconnectRequired
from pam.security.credentials import CredentialStore


@runtime_checkable
class OAuthStateStore(Protocol):
    """Persist short-lived OAuth state and its PKCE verifier until consumed."""

    def create(self, code_verifier: str) -> str:
        """Retain a PKCE verifier under a cryptographically strong state value."""

    def consume(self, state: str | None) -> str | None:
        """Atomically consume state and return its PKCE verifier, if valid."""


@dataclass(slots=True)
class InMemoryOAuthStateStore:
    """Local process-only one-time OAuth state storage."""

    _states: dict[str, str] = field(default_factory=dict)

    def create(self, code_verifier: str) -> str:
        state = secrets.token_urlsafe(32)
        self._states[state] = code_verifier
        return state

    def consume(self, state: str | None) -> str | None:
        if state is None:
            return None
        return self._states.pop(state, None)


def create_google_oauth_router(
    oauth_client: GoogleOAuthClient | None,
    state_store: OAuthStateStore,
    credential_store: CredentialStore | None,
) -> APIRouter:
    """Create local OAuth routes without exposing credentials in responses."""
    router = APIRouter()

    @router.get("/oauth/google/start")
    async def start_google_oauth() -> RedirectResponse:
        """Begin a local Google read-only authorization flow."""
        client = _configured_client(oauth_client)
        code_verifier = secrets.token_urlsafe(64)
        state = state_store.create(code_verifier)
        return RedirectResponse(client.authorization_url(state, code_verifier))

    @router.get("/oauth/google/callback")
    async def complete_google_oauth(
        state: str | None = None, code: str | None = None
    ) -> dict[str, str]:
        """Validate state, exchange a code, and encrypt only the refresh credential."""
        code_verifier = state_store.consume(state)
        if code_verifier is None:
            raise HTTPException(status_code=400, detail="invalid OAuth state")
        if code is None:
            raise HTTPException(
                status_code=400, detail="missing OAuth authorization code"
            )
        client = _configured_client(oauth_client)
        if credential_store is None:
            raise HTTPException(
                status_code=503, detail="Google OAuth is not configured"
            )
        try:
            credential_store.save(client.exchange_code(code, code_verifier))
        except GoogleReconnectRequired as error:
            raise HTTPException(
                status_code=400, detail="Google authorization failed"
            ) from error
        return {"status": "connected"}

    return router


def _configured_client(client: GoogleOAuthClient | None) -> GoogleOAuthClient:
    if client is None:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    return client
