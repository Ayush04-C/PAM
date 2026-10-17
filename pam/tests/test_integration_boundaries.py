"""Keep MCP adapters separate from conversation, transport and durable memory."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ADAPTERS = ("pam.mcp.calendar", "pam.mcp.driver")


def _matches(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".") for prefix in prefixes
    )


def _violations(path: Path, source: str) -> list[str]:
    """Inspect imports without importing application code or evaluating settings."""
    module_parts = path.with_suffix("").parts
    package = ".".join(module_parts[:-1])
    module = package if path.name == "__init__.py" else ".".join(module_parts)
    if _matches(module, _ADAPTERS):
        forbidden = (
            "pam.conversation.service",
            "pam.conversation.provider",
            "pam.conversation.bharatcode",
            "pam.conversation.gemini",
            "pam.conversation.factory",
            "pam.conversation.cli",
            "pam.telegram",
            "pam.memory",
        )
    elif _matches(module, ("pam.domain",)):
        forbidden = ("pam.mcp",)
    else:
        return []  # Composition roots may construct both capabilities.

    errors: list[str] = []
    for node in ast.walk(ast.parse(source, filename=path.as_posix())):
        if isinstance(node, ast.Import):
            imports = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = resolve_name("." * node.level + base, package)
            imports = [base, *(f"{base}.{alias.name}" for alias in node.names)]
        else:
            continue
        for imported in imports:
            if _matches(imported, forbidden):
                errors.append(f"{path.as_posix()}:{node.lineno}: forbidden {imported}")
    return errors


def test_repository_capabilities_respect_import_boundaries() -> None:
    errors = []
    for path in sorted((_ROOT / "pam").rglob("*.py")):
        relative = path.relative_to(_ROOT)
        if "tests" not in relative.parts:
            errors.extend(_violations(relative, path.read_text(encoding="utf-8")))
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("pam/mcp/driver.py", "import pam.conversation.bharatcode as provider"),
        ("pam/mcp/calendar.py", "from pam import telegram"),
        ("pam/mcp/driver.py", "from ..memory import service"),
        ("pam/mcp/calendar.py", "from pam.conversation import service"),
        ("pam/domain/models.py", "from ..mcp import driver"),
        ("pam/domain/models.py", "import pam.mcp.calendar"),
    ],
)
def test_forbidden_imports_report_path_and_line(path: str, source: str) -> None:
    errors = _violations(Path(path), source)
    assert errors
    assert all(error.startswith(f"{path}:1: forbidden pam.") for error in errors)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("pam/mcp/driver.py", "from pam.security.credentials import CredentialStore"),
        ("pam/mcp/driver.py", "from .calendar import format_tool_error"),
        (
            "pam/mcp/driver.py",
            "from pam.integrations.google_calendar import GoogleOAuthConfig",
        ),
        ("pam/mcp/driver.py", "from pam.config import Settings"),
        ("pam/mcp/driver.py", "from pam.conversation.models import DriveConsent"),
        ("pam/mcp/server.py", "from . import calendar, driver"),
        ("pam/mcp/driver.py", "import pam.conversation_helpers"),
        ("pam/security/credentials.py", "from cryptography.fernet import Fernet"),
        (
            "pam/conversation/factory.py",
            "from pam.mcp.server import create_mcp_server",
        ),
    ],
)
def test_allowed_imports_remain_available(path: str, source: str) -> None:
    assert _violations(Path(path), source) == []


def test_invalid_source_is_not_silently_accepted() -> None:
    with pytest.raises(SyntaxError):
        _violations(Path("pam/mcp/driver.py"), "from pam.domain import (")
