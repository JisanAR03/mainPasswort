"""Canary invariants: secrets never on disk, in logs, or in weak vaults ([S]).

I1: secrets never appear in plaintext in the vault file or its backups.
I2: secrets never reach logs or exception messages.
I3: a weak-KDF override exists only in the test fixtures.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core.errors import InvalidPassword
from personal_vault.core.models import SecretStr
from personal_vault.core.redaction import MARKER, RedactionFilter
from personal_vault.core.vault import VaultSession, open_vault

pytestmark = pytest.mark.security

ROOT = Path(__file__).resolve().parents[3]


def test_i1_secrets_never_on_disk(tmp_path: Path) -> None:
    canary = "CANARY-a3f9d2e1-77b4-4c1a"
    path = build_weak_vault(tmp_path / "vault.kdbx")
    with VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups") as session:
        session.add(make_login(password=SecretStr(canary)))
        session.save()
    assert canary.encode() not in path.read_bytes()
    assert WEAK_PASSWORD.encode() not in path.read_bytes()
    for backup in (tmp_path / "backups").glob("vault-*.kdbx"):
        assert canary.encode() not in backup.read_bytes()


def test_i2_secrets_never_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    canary = "CANARY-log-leak-51c8"
    redaction = RedactionFilter()
    redaction.add_secret(canary)
    logger = logging.getLogger("pv.test")
    logger.addFilter(redaction)
    with caplog.at_level(logging.INFO, logger="pv.test"):
        logger.info("tried the password %s and failed", canary)
    assert canary not in caplog.text
    assert MARKER in caplog.text


def test_i2_error_messages_never_contain_secrets(weak_vault_path: Path) -> None:
    canary = "CANARY-wrong-password-91db"
    with pytest.raises(InvalidPassword) as excinfo:
        open_vault(weak_vault_path, canary)
    assert canary not in str(excinfo.value)


def _uses_weak_override(path: Path) -> bool:
    """True when the file passes weak_override=True in a call (not a comment)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if (
                    keyword.arg == "weak_override"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    return True
    return False


def test_i3_weak_kdf_override_exists_only_in_test_fixtures() -> None:
    src = ROOT / "app" / "src"
    offenders_src = [str(p.relative_to(ROOT)) for p in src.rglob("*.py") if _uses_weak_override(p)]
    assert offenders_src == []
    tests = ROOT / "app" / "tests"
    offenders_tests = [
        str(p.relative_to(ROOT))
        for p in tests.rglob("*.py")
        if _uses_weak_override(p) and "fixtures" not in p.parts
    ]
    assert offenders_tests == []


def test_i8_plaintext_export_requires_reauth_and_confirmation() -> None:
    """Every call to export_csv must sit in a function that re-checks the
    master password (open_vault) and compares a typed confirmation."""
    src = ROOT / "app" / "src"
    export_calls = 0
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "export_csv"
                ):
                    export_calls += 1
                    calls = {
                        call.func.id
                        for call in ast.walk(node)
                        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    }
                    has_confirmation = any(
                        isinstance(child, ast.Compare) for child in ast.walk(node)
                    )
                    assert "open_vault" in calls, (
                        f"{path}: export_csv called without a master-password re-check"
                    )
                    assert has_confirmation, (
                        f"{path}: export_csv called without a typed confirmation"
                    )
    assert export_calls >= 1  # the guarded UI path exists at all
