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
    assert "presentation fields instead of calculating durations" in instruction
    assert "specific-time question" in instruction
    assert (
        "Only recommend an exact time range when it appears verbatim in candidate_slots"
        in instruction
    )
    assert "Never derive a new start or end time from a free window" in instruction
    for forbidden_action in ("hold", "reserve", "book", "create", "add", "block"):
        assert forbidden_action in instruction
