"""Tests for structured logging redaction."""

import json
import logging

from pam.logging import REDACTED, JsonFormatter


def test_secret_fields_and_values_are_redacted() -> None:
    record = logging.LogRecord(
        name="pam.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="authorization=plain-text-secret",
        args=(),
        exc_info=None,
    )
    record.api_key = "also-plain-text"  # type: ignore[attr-defined]

    output = JsonFormatter().format(record)
    payload = json.loads(output)

    assert payload["api_key"] == REDACTED
    assert "plain-text-secret" not in output
    assert "also-plain-text" not in output
