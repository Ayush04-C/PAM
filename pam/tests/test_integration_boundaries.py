"""Offline import guards for independent Calendar and future Drive capabilities."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CALENDAR = (
    "pam.domain",
    "pam.application",
    "pam.mcp.calendar",
    "pam.mcp.server",
    "pam.integrations.google_calendar",
    "pam.integrations.google_wiring",
)
_SHARED = ("pam.config", "pam.logging", "pam.security", "pam.integrations.google_oauth")


def _matches(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".") for prefix in prefixes
    )


def _violations(path: Path, source: str) -> list[str]:
    """Inspect imports without importing application code or evaluating settings."""
    module_parts = path.with_suffix("").parts
    package = ".".join(module_parts[:-1])
    module = package if path.name == "__init__.py" else ".".join(module_parts)
    if _matches(module, ("pam.drive",)):
        forbidden = (*_CALENDAR, "pam.conversation", "pam.telegram", "pam.memory")
    elif _matches(module, _CALENDAR):
        forbidden = ("pam.drive",)
    elif _matches(module, _SHARED):
        forbidden = (*_CALENDAR, "pam.drive")
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
        ("pam/domain/models.py", "import pam.drive.reader as reader"),
        ("pam/mcp/server.py", "from pam import drive"),
        ("pam/domain/models.py", "from ..drive import reader"),
        ("pam/drive/reader.py", "from pam.domain import CalendarEvent"),
        ("pam/drive/reader.py", "from ..application import AvailabilityService"),
        ("pam/drive/mcp/server.py", "from ...mcp.calendar import CalendarMcpAdapter"),
        ("pam/drive/__init__.py", "from ..integrations import google_calendar"),
        ("pam/drive/service.py", "from pam.memory import service"),
        ("pam/drive/google_drive.py", "import pam.conversation.bharatcode"),
        ("pam/drive/mcp/tools.py", "from pam.telegram import adapter"),
        ("pam/security/credentials.py", "from ..drive import models"),
        ("pam/integrations/google_oauth.py", "import pam.integrations.google_calendar"),
    ],
)
def test_forbidden_imports_report_path_and_line(path: str, source: str) -> None:
    errors = _violations(Path(path), source)
    assert errors
    assert all(error.startswith(f"{path}:1: forbidden pam.") for error in errors)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("pam/drive/reader.py", "from pam.security.credentials import CredentialStore"),
        ("pam/drive/mcp/server.py", "from ..service import DriveService"),
        ("pam/drive/__init__.py", "from . import models"),
        ("pam/drive/wiring.py", "from pam.config import Settings"),
        ("pam/drive/mcp/server.py", "from pam.mcp.config import McpServerLaunchConfig"),
        ("pam/drive/reader.py", "import pam.domain_helpers"),
        ("pam/security/credentials.py", "from cryptography.fernet import Fernet"),
        (
            "pam/conversation/factory.py",
            "from pam.drive.wiring import create_drive_service",
        ),
    ],
)
def test_allowed_imports_remain_available(path: str, source: str) -> None:
    assert _violations(Path(path), source) == []


def test_invalid_source_is_not_silently_accepted() -> None:
    with pytest.raises(SyntaxError):
        _violations(Path("pam/drive/reader.py"), "from pam.domain import (")
