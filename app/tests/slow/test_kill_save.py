"""I3: killing the process mid-save never corrupts the vault (slow).

Spawns the child 200 times, kills it at a random moment each time, and checks
that the vault still opens afterwards — or that recovery can restore it from a
backup. Runs only with ``pytest -m slow``.
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest
from personal_vault.core import storage
from personal_vault.core.errors import VaultCorrupted
from personal_vault.core.vault import open_vault

pytestmark = pytest.mark.slow

CHILD = Path(__file__).resolve().parents[1] / "fixtures" / "kill_save_child.py"
SRC = Path(__file__).resolve().parents[2] / "src"
PASSWORD = "kill-save-password"
KILLS = 200


def test_kill_during_save_never_corrupts(tmp_path: Path) -> None:
    vault_path = tmp_path / "vault.kdbx"
    backups_dir = tmp_path / "backups"
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    rng = random.Random(20261015)

    def verifier(path: Path) -> None:
        open_vault(path, PASSWORD)

    for _ in range(KILLS):
        proc = subprocess.Popen(
            [sys.executable, str(CHILD), str(vault_path), str(backups_dir), PASSWORD],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if rng.random() < 0.2:
            time.sleep(rng.uniform(0, 0.03))  # kill during startup/first save
        else:
            deadline = time.monotonic() + 10
            while not vault_path.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.005)
            time.sleep(rng.uniform(0, 0.04))  # kill during a later save
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

        if not vault_path.exists():
            continue  # killed before the first save: nothing to lose
        try:
            open_vault(vault_path, PASSWORD)
        except VaultCorrupted:
            recovered = storage.recover(vault_path, backups_dir, verifier)
            assert recovered is not None, "corrupted vault with no good backup"
            open_vault(vault_path, PASSWORD)

    # After 200 kills the vault must still be a valid, openable vault.
    open_vault(vault_path, PASSWORD)
