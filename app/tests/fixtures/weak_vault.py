"""The ONLY place in the repo that may create a weak-KDF vault ([S]).

Production refuses KDF memory below 64 MiB; these fixtures pass the test-only
override (8 MiB, 1 iteration) so the suite runs fast. A security test scans the
tree and fails if weak_override=True appears anywhere else.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from personal_vault.core import kdf
from personal_vault.core.models import LoginEntry, SecretStr
from personal_vault.core.vault import VaultSession, open_vault
from pykeepass import create_database

WEAK_PASSWORD = "test-master-password"
WEAK_MEMORY_MIB = 8
WEAK_ITERATIONS = 1


def build_weak_vault(path: Path, password: str = WEAK_PASSWORD) -> Path:
    """Write a weak-KDF vault at ``path`` and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    kp = create_database(str(path), password=password)
    kdf.apply_kdf(
        kp,
        iterations=WEAK_ITERATIONS,
        memory_mib=WEAK_MEMORY_MIB,
        weak_override=True,
    )
    kp.add_group(kp.root_group, "Logins")
    kp.save()
    return path


def weak_verifier(password: str = WEAK_PASSWORD):
    """A storage verifier that opens the file with the fixture password."""

    def verify(path: Path) -> None:
        open_vault(path, password)

    return verify


def make_login(**overrides: Any) -> LoginEntry:
    """A valid LoginEntry with every required field, for tests to tweak."""
    now = datetime.now(UTC)
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "title": "Example Site",
        "username": "user@example.com",
        "password": SecretStr("correct horse battery staple"),
        "urls": ["https://example.com"],
        "notes": "",
        "tags": [],
        "match_subdomains": False,
        "created_at": now,
        "updated_at": now,
    }
    fields.update(overrides)
    return LoginEntry(**fields)


@pytest.fixture
def weak_vault_path(tmp_path: Path) -> Path:
    """A vault file created with the test-only weak KDF."""
    return build_weak_vault(tmp_path / "vault.kdbx")


@pytest.fixture
def weak_session(tmp_path: Path) -> VaultSession:
    """An open VaultSession over a weak-KDF vault with its own backups dir."""
    path = build_weak_vault(tmp_path / "vault.kdbx")
    return VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups")
