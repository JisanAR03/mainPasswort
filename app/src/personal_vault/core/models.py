"""Domain model types shared by the UI and the bridge ([S]).

The UI and the bridge use these types and never touch pykeepass objects, which
keeps the library replaceable. Field rules come from docs/specs/data-model.md.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


class SecretStr:
    """Holds a secret; str() and repr() print '***' so it never lands in logs.

    The real value is only reachable through reveal(), on purpose: f-strings,
    %-formatting and log calls all go through __str__/__format__, which redact.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return "***"

    def __repr__(self) -> str:
        return "SecretStr(***)"

    def __format__(self, format_spec: str) -> str:
        # Formatting must redact too: format the marker, never the value.
        return format("***", format_spec)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretStr):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)

    def __len__(self) -> int:
        return len(self._value)


@dataclass(frozen=True)
class LoginSummary:
    """What search results and the browser list get; no secrets."""

    id: uuid.UUID
    title: str
    username: str
    hosts: tuple[str, ...]


@dataclass
class LoginEntry:
    """What the edit form gets."""

    id: uuid.UUID
    title: str
    username: str
    password: SecretStr
    urls: list[str]
    notes: str
    tags: list[str]
    match_subdomains: bool
    created_at: datetime
    updated_at: datetime
