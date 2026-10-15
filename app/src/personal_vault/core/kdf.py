"""Argon2id key derivation parameters and calibration ([S]).

The spec fixes memory (128 MiB) and parallelism (2) and calibrates the
iteration count so an unlock takes about one second on this machine.
Production refuses KDF memory below 64 MiB; only tests may pass the weak
override (8 MiB, 1 iteration), so a weak vault can never be created by
accident.

Everything here patches pykeepass's in-memory header only; the derivation
itself is done by pykeepass when the vault is opened (AGENTS rule 2).
"""

from __future__ import annotations

import secrets
import shutil
import tempfile
import time
from pathlib import Path

from pykeepass import PyKeePass, create_database

DEFAULT_MEMORY_MIB = 128
MIN_MEMORY_MIB = 64
PARALLELISM = 2
TARGET_UNLOCK_SECONDS = 1.0
ARGON2_VERSION_13 = 0x13
KDF_UUID_ARGON2ID = b"\x9e)\x8b\x19V\xdbGs\xb2=\xfc>\xc6\xf0\xa1\xe6"

UUID_KEY = "$UUID"
VERSION_KEY = "V"
ITERATIONS_KEY = "I"
MEMORY_KEY = "M"
PARALLELISM_KEY = "P"
AESKDF_KEYS = ("K", "A")  # AES-KDF leftovers in the blank database header


def apply_kdf(
    kp: PyKeePass,
    *,
    iterations: int,
    memory_mib: int = DEFAULT_MEMORY_MIB,
    parallelism: int = PARALLELISM,
    weak_override: bool = False,
) -> None:
    """Patch the header so the next save writes the requested KDF parameters.

    ``weak_override=True`` exists for the test fixture only (8 MiB, 1
    iteration); production code never passes it.
    """
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if parallelism < 1:
        raise ValueError("parallelism must be >= 1")
    if memory_mib < MIN_MEMORY_MIB and not weak_override:
        raise ValueError(
            f"refusing {memory_mib} MiB KDF memory: the production minimum is "
            f"{MIN_MEMORY_MIB} MiB (weak_override is for tests only)"
        )
    params = kp.kdbx.header.value.dynamic_header.kdf_parameters.data.dict
    params[UUID_KEY].value = KDF_UUID_ARGON2ID
    params[VERSION_KEY].value = ARGON2_VERSION_13
    params[ITERATIONS_KEY].value = iterations
    params[MEMORY_KEY].value = memory_mib * 1024 * 1024
    params[PARALLELISM_KEY].value = parallelism
    for key in AESKDF_KEYS:
        params.pop(key, None)


def calibrate_iterations(
    memory_mib: int = DEFAULT_MEMORY_MIB,
    target_seconds: float = TARGET_UNLOCK_SECONDS,
) -> int:
    """Measure real pykeepass unlocks and extrapolate to the target duration."""
    scratch = Path(tempfile.mkdtemp(prefix="pv-calibrate-"))
    try:

        def unlock_time(iterations: int) -> float:
            password = secrets.token_hex(16)  # throwaway, never reused
            path = scratch / f"cal-{iterations}.kdbx"
            kp = create_database(str(path), password=password)
            apply_kdf(kp, iterations=iterations, memory_mib=memory_mib)
            kp.save()
            start = time.perf_counter()
            PyKeePass(str(path), password=password)
            return time.perf_counter() - start

        slope = unlock_time(2) - unlock_time(1)
        if slope <= 0:
            return 1
        return max(1, int(target_seconds / slope))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
