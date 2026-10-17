"""Configured provider selection shared by local conversation transports."""

from __future__ import annotations

from pam.config import Settings
from pam.conversation.bharatcode import BharatCodeProvider
from pam.conversation.gemini import GeminiProvider
from pam.conversation.provider import ModelProvider


def configured_model_destination(settings: Settings) -> str | None:
    """Identify the configured transfer target without constructing SDK clients."""
    if settings.model_provider == "bharatcode":
        return (
            f"bharatcode:{settings.bharatcode_base_url.rstrip('/')}"
            f"|{settings.bharatcode_model}"
        )
    if settings.model_provider == "gemini":
        return (
            f"gemini:https://generativelanguage.googleapis.com|{settings.gemini_model}"
        )
    return None


def create_model_provider(settings: Settings) -> ModelProvider:
    """Construct only the explicitly selected provider; never auto-fallback."""
    if settings.model_provider == "bharatcode":
        if settings.bharatcode_api_key is None:
            raise ValueError("PAM_BHARATCODE_API_KEY is required")
        return BharatCodeProvider(
            settings.bharatcode_api_key.get_secret_value(),
            settings.bharatcode_model,
            settings.bharatcode_base_url,
        )
    if settings.model_provider == "gemini":
        if settings.gemini_api_key is None:
            raise ValueError("PAM_GEMINI_API_KEY is required")
        return GeminiProvider(
            settings.gemini_api_key.get_secret_value(), settings.gemini_model
        )
    raise ValueError("A hosted model provider is required for this command")
