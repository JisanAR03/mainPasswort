"""M1-03: atomic writes, corruption detection, backups and recovery ([S])."""

from __future__ import annotations

import json
import random
import struct
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, weak_verifier
from personal_vault.core import storage
from personal_vault.core.errors import InvalidPassword, VaultCorrupted
from personal_vault.core.vault import open_vault

pytestmark = pytest.mark.integration


def test_atomic_write_replaces_target(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    storage.atomic_write(target, lambda t: t.write_text("new", encoding="utf-8"))
    assert target.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob("*.tmp-*")) == []


def test_failed_verifier_never_replaces_target(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("old", encoding="utf-8")

    def writer(tmp: Path) -> None:
        tmp.write_text("new", encoding="utf-8")

    def failing_verifier(tmp: Path) -> None:
        raise AssertionError("verifier refused")

    with pytest.raises(AssertionError):
        storage.atomic_write(target, writer, failing_verifier)
    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob("*.tmp-*")) == []


def test_atomic_write_json_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    storage.atomic_write_json(target, {"a": 1, "b": [2, 3]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "b": [2, 3]}


def test_backup_names_are_stamped_and_sequenced(tmp_path: Path) -> None:
    target = tmp_path / "vault.kdbx"
    target.write_bytes(b"v1")
    backups = tmp_path / "backups"
    first = storage.backup_current(target, backups)
    second = storage.backup_current(target, backups)
    assert first is not None and first.name.startswith("vault-")
    assert first.name.endswith("-0001.kdbx")
    assert second is not None and second.name.endswith("-0002.kdbx")
    assert first.read_bytes() == b"v1"
    assert storage.backup_current(tmp_path / "missing.kdbx", backups) is None


def test_rotate_keeps_recent_and_daily(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    # Same day, 10 backups: only the newest 3 survive with keep_recent=3.
    for i in range(10):
        (backups / f"vault-20261015T1200{i:02d}Z-0001.kdbx").write_bytes(b"x")
    storage.rotate(backups, keep_recent=3, keep_daily=30)
    assert len(list(backups.glob("vault-*.kdbx"))) == 3
    # Five older days, one backup each: keep_recent=2 plus the 2 newest days.
    for i in range(5):
        (backups / f"vault-2026101{i}T120000Z-0001.kdbx").write_bytes(b"x")
    storage.rotate(backups, keep_recent=2, keep_daily=2)
    kept = sorted(p.name for p in backups.glob("vault-*.kdbx"))
    assert kept == [
        "vault-20261014T120000Z-0001.kdbx",  # newest of day 14 (daily)
        "vault-20261015T120008Z-0001.kdbx",  # recent
        "vault-20261015T120009Z-0001.kdbx",  # recent + newest of day 15
    ]


def test_save_with_backup_keeps_previous_version(tmp_path: Path) -> None:
    target = tmp_path / "vault.kdbx"
    backups = tmp_path / "backups"
    storage.save_with_backup(
        target, lambda t: t.write_text("v1", encoding="utf-8"), lambda t: None, backups, 5, 5
    )
    storage.save_with_backup(
        target, lambda t: t.write_text("v2", encoding="utf-8"), lambda t: None, backups, 5, 5
    )
    assert target.read_text(encoding="utf-8") == "v2"
    saved = [p.read_text(encoding="utf-8") for p in backups.glob("vault-*.kdbx")]
    assert saved == ["v1"]


def test_byte_flips_are_detected(tmp_path: Path) -> None:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    original = path.read_bytes()
    rng = random.Random(1234)
    for _ in range(200):
        offset = rng.randrange(len(original))
        corrupt = bytearray(original)
        corrupt[offset] ^= 0xFF
        bad = tmp_path / "bad.kdbx"
        bad.write_bytes(corrupt)
        if offset >= 1024:
            # Past the header: an authenticated-payload checksum failure.
            with pytest.raises(VaultCorrupted):
                open_vault(bad, WEAK_PASSWORD)
        else:
            # Header region: the pre-KDF header check refuses, or the header
            # HMAC fails against the derived key.
            with pytest.raises((InvalidPassword, VaultCorrupted)):
                open_vault(bad, WEAK_PASSWORD)


def test_every_header_byte_flip_is_refused_before_kdf(tmp_path: Path) -> None:
    # Two pykeepass 4.2.0 gaps the pre-KDF header check closes:
    # - a flipped KDF-parameter byte can make argon2 run effectively forever,
    #   because the key is derived before the header checksum is verified;
    # - a flipped major-version byte silently skips the whole body (construct's
    #   Switch defaults to Pass), so a garbage vault used to open successfully.
    # Every byte of the raw header must be refused before argon2 starts.
    path = build_weak_vault(tmp_path / "vault.kdbx")
    original = path.read_bytes()
    pos = 12
    while original[pos] != 0:  # walk the size-prefixed fields to EndOfHeader
        (size,) = struct.unpack_from("<I", original, pos + 1)
        pos += 5 + size
    for offset in range(0, pos):
        corrupt = bytearray(original)
        corrupt[offset] ^= 0xFF
        bad = tmp_path / "bad.kdbx"
        bad.write_bytes(corrupt)
        with pytest.raises(VaultCorrupted):
            open_vault(bad, WEAK_PASSWORD)


def test_truncation_is_detected(tmp_path: Path) -> None:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    original = path.read_bytes()
    for cut in (10, len(original) // 2, len(original) - 1):
        bad = tmp_path / "cut.kdbx"
        bad.write_bytes(original[:cut])
        with pytest.raises(VaultCorrupted):
            open_vault(bad, WEAK_PASSWORD)


def test_recover_restores_newest_good_backup(tmp_path: Path) -> None:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    backups = tmp_path / "backups"
    storage.backup_current(path, backups)
    path.write_bytes(b"garbage")  # destroy the live file
    with pytest.raises(VaultCorrupted):
        open_vault(path, WEAK_PASSWORD)
    restored = storage.recover(path, backups, weak_verifier())
    assert restored is not None
    open_vault(path, WEAK_PASSWORD)
    # Nothing to recover when no good backup exists.
    assert storage.find_newest_good_backup(tmp_path / "empty", weak_verifier()) is None
