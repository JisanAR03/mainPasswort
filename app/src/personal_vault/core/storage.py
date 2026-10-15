"""Atomic, verified file writes with rotating backups ([S]).

Every save goes through here: write a temp file in the same folder, verify it
by reading it back (for vaults: decrypt it), then rename it over the target.
A crash at any point leaves either the old file or the new file, and that
file decrypts (invariant I3).
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from personal_vault.core.errors import VaultError

Writer = Callable[[Path], None]
Verifier = Callable[[Path], None]


def atomic_write(path: Path, writer: Writer, verifier: Verifier | None = None) -> None:
    """Write ``path`` atomically: temp file in the same folder -> verify -> rename."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        writer(tmp)
        if verifier is not None:
            verifier(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_write_json(path: Path, data: Mapping[str, object]) -> None:
    """Atomically write a JSON file, re-reading it before the rename."""
    encoded = json.dumps(data, indent=2).encode("utf-8") + b"\n"

    def writer(tmp: Path) -> None:
        tmp.write_bytes(encoded)

    def verifier(tmp: Path) -> None:
        json.loads(tmp.read_text(encoding="utf-8"))

    atomic_write(path, writer, verifier)


def backup_current(path: Path, backups_dir: Path) -> Path | None:
    """Copy the current file into backups/ with a timestamp+sequence name."""
    if not path.exists():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "Z"
    seq = sum(1 for _ in backups_dir.glob(f"vault-{stamp}-*.kdbx")) + 1
    backup = backups_dir / f"vault-{stamp}-{seq:04d}.kdbx"
    shutil.copyfile(path, backup)
    return backup


def rotate(backups_dir: Path, keep_recent: int, keep_daily: int) -> None:
    """Keep the newest ``keep_recent`` backups plus one per day for ``keep_daily`` days."""
    backups = sorted(backups_dir.glob("vault-*.kdbx"))
    if len(backups) <= keep_recent:
        return
    recent = set(backups[-keep_recent:])
    newest_per_day: dict[str, Path] = {}
    for backup in backups:
        day = backup.name[6:14]  # YYYYMMDD out of vault-YYYYMMDDT...
        newest_per_day[day] = backup  # sorted order: later entries are newer
    daily_keep = {path for _, path in sorted(newest_per_day.items(), reverse=True)[:keep_daily]}
    for backup in backups:
        if backup not in recent and backup not in daily_keep:
            backup.unlink(missing_ok=True)


def save_with_backup(
    path: Path,
    writer: Writer,
    verifier: Verifier,
    backups_dir: Path,
    keep_recent: int,
    keep_daily: int,
) -> None:
    """Back up the current file, atomically write the new one, then rotate."""
    backup_current(path, backups_dir)
    atomic_write(path, writer, verifier)
    rotate(backups_dir, keep_recent, keep_daily)


def find_newest_good_backup(backups_dir: Path, verifier: Verifier) -> Path | None:
    """Newest backup that verifies (decrypts), or None when none is good."""
    for backup in sorted(backups_dir.glob("vault-*.kdbx"), reverse=True):
        try:
            verifier(backup)
        except VaultError:
            continue
        return backup
    return None


def recover(path: Path, backups_dir: Path, verifier: Verifier) -> Path | None:
    """Restore the newest good backup over ``path``; returns the backup used."""
    backup = find_newest_good_backup(backups_dir, verifier)
    if backup is None:
        return None

    def writer(tmp: Path) -> None:
        shutil.copyfile(backup, tmp)

    atomic_write(path, writer, verifier)
    return backup
