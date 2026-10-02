"""Configured selection of PAM's long-term memory backend."""

from __future__ import annotations

from pam.config import Settings
from pam.memory.service import DisabledMemoryService, MemoryService
from pam.memory.supermemory import SupermemoryMemoryService


def create_memory_service(settings: Settings) -> MemoryService:
    """Create the explicitly selected memory backend without fallback."""
    if settings.memory_backend == "disabled":
        return DisabledMemoryService()
    if settings.supermemory_api_key is None:
        raise ValueError("PAM_SUPERMEMORY_API_KEY is required")
    return SupermemoryMemoryService(
        settings.supermemory_api_key.get_secret_value(),
        base_url=settings.supermemory_base_url,
        max_recalled_items=settings.memory_max_recalled_items,
        max_content_chars=settings.memory_max_content_chars,
    )
