"""Stage 2 read/transfer permission and payload validation tests."""

from dataclasses import replace

import pytest

from pam.conversation.models import DriveConsent, DriveConsentRequired, DriveContext
from pam.memory.models import MemoryOwnerId

OWNER = MemoryOwnerId("telegram:100")
OTHER = MemoryOwnerId("telegram:200")
DESTINATION = "test-provider:model-a"
CONSENT = DriveConsent(OWNER, DESTINATION, True, True, True)


@pytest.mark.parametrize("text", ["", "x" * 20_001])
def test_invalid_context_is_rejected_without_echoing_payload(text) -> None:
    with pytest.raises(ValueError, match="invalid or oversized Drive context"):
        DriveContext(text)


def test_metadata_permission_does_not_grant_content_transfer() -> None:
    metadata = replace(CONSENT, allow_content_transfer=False)
    assert (
        metadata.authorize_transfer(OWNER, DESTINATION, "metadata").kind == "metadata"
    )
    with pytest.raises(DriveConsentRequired):
        metadata.authorize_transfer(OWNER, DESTINATION, "content")


def test_read_and_model_transfer_are_distinct_permissions() -> None:
    denied = DriveConsent(OWNER, DESTINATION)
    with pytest.raises(DriveConsentRequired, match="read consent"):
        denied.require_read(OWNER)
    read_only = replace(denied, allow_read=True)
    read_only.require_read(OWNER)
    with pytest.raises(DriveConsentRequired, match="model-transfer consent"):
        read_only.authorize_transfer(OWNER, DESTINATION, "metadata")
    with pytest.raises(DriveConsentRequired):
        read_only.require_read(OTHER)
