"""Safe in-memory audit metadata for the internal HTTP API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Approved metadata for an availability operation."""

    operation: str
    request_id: str
    outcome: str
    start_date: date
    end_date: date
    timezone: str


@runtime_checkable
class AuditSink(Protocol):
    """Record approved audit metadata without storing request content."""

    def record(self, event: AuditEvent) -> None:
        """Store one safe audit event."""


@dataclass(slots=True)
class InMemoryAuditSink:
    """Small test and local-development audit sink."""

    events: list[AuditEvent] = field(default_factory=list)

    def record(self, event: AuditEvent) -> None:
        """Append a safe audit event."""
        self.events.append(event)
