"""Internal HTTP boundary for weekly availability."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from pam.api.audit import AuditEvent, AuditSink
from pam.application import (
    AvailabilityService,
    CalendarUnavailable,
    InvalidAvailabilityRequest,
)
from pam.logging import request_id_context


class AvailabilityRequest(BaseModel):
    """Typed request body for the local availability endpoint."""

    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    timezone: str


class AvailabilityResponse(BaseModel):
    """Stable response body containing the domain-formatted summary."""

    availability: str


def create_availability_router(
    service: AvailabilityService, audit_sink: AuditSink
) -> APIRouter:
    """Create an endpoint router bound to explicit application dependencies."""
    router = APIRouter()

    @router.post("/availability", response_model=AvailabilityResponse)
    async def get_availability(request: AvailabilityRequest) -> AvailabilityResponse:
        """Return a deterministic local weekly availability summary."""
        timezone = _resolve_timezone(request.timezone)
        try:
            summary = service.get_weekly_availability(
                request.start_date, request.end_date, timezone
            )
        except InvalidAvailabilityRequest as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except CalendarUnavailable as error:
            raise HTTPException(
                status_code=503, detail="calendar is unavailable"
            ) from error

        request_id = request_id_context.get()
        if request_id is None:
            raise RuntimeError("request ID middleware is required")
        audit_sink.record(
            AuditEvent(
                operation="get_weekly_availability",
                request_id=request_id,
                outcome="success",
                start_date=request.start_date,
                end_date=request.end_date,
                timezone=request.timezone,
            )
        )
        return AvailabilityResponse(availability=summary)

    return router


def _resolve_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(
            status_code=400, detail="only Asia/Kolkata is supported"
        ) from error
