"""Bounded, ephemeral verified file references; never an authorization cache."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pam.conversation.models import DriveBoundary

_ID = r"[A-Za-z0-9_-]{1,256}"
_REFERENT = re.compile(
    r"\b(?:(?:this|that|selected)\s+(?:file|document|one)|the one)\b", re.I
)
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}


def google_file_ids(text: str) -> frozenset[str]:
    """Parse recognized HTTPS Google links locally; never follow their URLs."""
    identifiers = set()
    for raw in re.findall(r"https?://[^\s<>]+", text):
        try:
            url = urlsplit(raw.rstrip(".,);]"))
            if url.scheme != "https" or url.username or url.password or url.port:
                continue
            if url.netloc == "drive.google.com":
                match = re.fullmatch(r"/file/d/(" + _ID + r")/(?:view|edit)", url.path)
                value = match[1] if match else None
                if url.path == "/open":
                    values = parse_qs(url.query).get("id", [])
                    value = values[0] if len(values) == 1 else None
            elif url.netloc == "docs.google.com":
                match = re.fullmatch(
                    r"/(?:document|spreadsheets|presentation)/d/("
                    + _ID
                    + r")/(?:edit|view|preview)",
                    url.path,
                )
                value = match[1] if match else None
            else:
                continue
            if value and re.fullmatch(_ID, value):
                identifiers.add(value)
        except ValueError:
            continue
    return frozenset(identifiers)


@dataclass(frozen=True, slots=True)
class FileReferences:
    """Latest verified candidate list and its one query-bound continuation."""

    boundary: DriveBoundary = field(repr=False)
    expires_at: datetime
    files: tuple[dict[str, Any], ...] = field(default=(), repr=False)
    query: str | None = field(default=None, repr=False)
    page_size: int = 10
    next_page_token: str | None = field(default=None, repr=False)
    incomplete_search: bool = False

    def valid(self, boundary: DriveBoundary | None, now: datetime) -> bool:
        return self.boundary == boundary and now < self.expires_at

    @classmethod
    def from_result(
        cls,
        previous: FileReferences | None,
        boundary: DriveBoundary,
        name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        now: datetime,
    ) -> FileReferences | None:
        if result.get("error") is not None:
            if (
                previous
                and result["error"].get("code") == "unavailable"
                and name == "drive_get_file_metadata"
            ):
                return replace(
                    previous,
                    files=tuple(
                        file
                        for file in previous.files
                        if file["file_id"] != arguments.get("file_id")
                    ),
                )
            if previous and result["error"].get("code") == "invalid_page_token":
                return replace(previous, next_page_token=None)
            return previous
        files = tuple(dict(file) for file in result.get("files", []))
        if name == "drive_search_files":
            return cls(
                boundary,
                now + timedelta(minutes=30),
                files[:50],
                arguments.get("name"),
                arguments.get("page_size", 10),
                result.get("next_page_token"),
                bool(result.get("incomplete_search")),
            )
        if not files:
            return previous
        existing = previous.files if previous else ()
        updates = {file["file_id"]: file for file in files}
        merged = tuple(updates.pop(file["file_id"], file) for file in existing)
        merged = (*merged, *updates.values())[:50]
        if previous:
            # A metadata refresh must not extend the search cursor's lifetime.
            return replace(previous, files=merged)
        return cls(boundary, now + timedelta(minutes=30), merged)

    def context(self, selected: str | None = None) -> str:
        return json.dumps(
            {
                "verified_file_choices": [
                    dict(file, choice=i) for i, file in enumerate(self.files, 1)
                ],
                "selected_file_id": selected,
                "search": {
                    "name": self.query,
                    "page_size": self.page_size,
                    "next_page_token": self.next_page_token,
                    "incomplete_search": self.incomplete_search,
                },
            },
            ensure_ascii=False,
        )

    def display(self) -> str:
        rows = ["Verified Drive choices (metadata only):"]
        for i, file in enumerate(self.files, 1):
            rows.append(
                f"{i}. {json.dumps(file['name'], ensure_ascii=False)}\n"
                f"   {file['source_url']}"
            )
        if not self.files:
            rows.append("No matching files on this page.")
        if self.incomplete_search:
            rows.append("Google reported an incomplete search; more files may exist.")
        if self.next_page_token:
            rows.append("More results are available. Ask for the next page.")
        return "\n".join(rows)


def selection(
    text: str, references: FileReferences | None
) -> tuple[str | None, str | None]:
    """Resolve common explicit selections; ambiguous references never guess."""
    linked = google_file_ids(text)
    if len(linked) == 1:
        return next(iter(linked)), None
    if re.fullmatch(
        r"(?:show (?:the )?)?next (?:drive )?page[.!?]?", text.strip(), re.I
    ):
        if references is None or references.next_page_token is None:
            return (
                None,
                "No saved next Drive page is available. Please start a new search.",
            )
        return None, None
    ordinal = re.search(
        r"\b(first|second|third|fourth|fifth)\s+(?:one|file|document)\b", text, re.I
    )
    numbered = re.search(
        r"\b(?:file|document|choice|number)\s*#?\s*(\d{1,3})\b", text, re.I
    )
    bare_number = re.fullmatch(r"\s*(\d{1,2})\s*", text)
    index = (
        _ORDINALS[ordinal[1].lower()]
        if ordinal
        else int(numbered[1])
        if numbered
        else int(bare_number[1])
        if bare_number
        else None
    )
    contextual = index is not None or bool(_REFERENT.search(text))
    if references and not contextual:
        names = [file["name"] for file in references.files]
        duplicates = {name for name in names if names.count(name) > 1}
        contextual = any(name.casefold() in text.casefold() for name in duplicates)
    if not contextual:
        return None, None
    if references is None or not references.files:
        return (
            None,
            "That file reference is unavailable or expired. "
            "Please search again or provide a Google Drive link.",
        )
    if index is not None:
        if not 1 <= index <= len(references.files):
            return (
                None,
                "Please choose a number from the current Drive choices.\n\n"
                + references.display(),
            )
        return str(references.files[index - 1]["file_id"]), None
    if len(references.files) == 1:
        return str(references.files[0]["file_id"]), None
    return (
        None,
        "Which file do you mean? Please choose its number.\n\n" + references.display(),
    )
