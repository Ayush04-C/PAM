"""Tests for deterministic model policy wording."""

from datetime import datetime

from pam.conversation.system_prompt import build_system_instruction
from pam.domain import DISPLAY_TIMEZONE


def test_system_prompt_does_not_promise_passive_memory_persistence() -> None:
    instruction = build_system_instruction(
        datetime(2026, 10, 2, 9, 30, tzinfo=DISPLAY_TIMEZONE)
    )

    assert "Do not promise that a natural user statement was saved" in instruction
    assert (
        "Only an explicit successful Remember request may be acknowledged"
        in instruction
    )
