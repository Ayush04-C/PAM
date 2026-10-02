"""Provider-neutral durable-memory value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryOwnerId:
    """Stable, transport-neutral identity for one user's durable memory."""

    value: str


@dataclass(frozen=True, slots=True)
class RecalledMemory:
    """Bounded untrusted memory context supplied to a model."""

    content: str
