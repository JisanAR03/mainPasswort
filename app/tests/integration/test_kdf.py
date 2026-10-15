"""M1-03: KDF parameters written into the vault header ([S])."""

from __future__ import annotations

from pathlib import Path

import pytest
from personal_vault.core import kdf
from personal_vault.core.vault import open_vault
from pykeepass import PyKeePass, create_database

pytestmark = pytest.mark.integration


def _header_params(path: Path):
    opened = PyKeePass(str(path), password="pw")
    return opened.kdbx.header.value.dynamic_header.kdf_parameters.data.dict


def test_apply_kdf_writes_argon2id_parameters(tmp_path: Path) -> None:
    path = tmp_path / "vault.kdbx"
    kp = create_database(str(path), password="pw")
    kdf.apply_kdf(kp, iterations=7, memory_mib=64, parallelism=2)
    kp.save()
    params = _header_params(path)
    assert bytes(params[kdf.UUID_KEY].value) == kdf.KDF_UUID_ARGON2ID
    assert int(params[kdf.VERSION_KEY].value) == kdf.ARGON2_VERSION_13
    assert int(params[kdf.ITERATIONS_KEY].value) == 7
    assert int(params[kdf.MEMORY_KEY].value) == 64 * 1024 * 1024
    assert int(params[kdf.PARALLELISM_KEY].value) == 2


def test_apply_kdf_round_trip_opens(tmp_path: Path) -> None:
    path = tmp_path / "vault.kdbx"
    kp = create_database(str(path), password="pw")
    kdf.apply_kdf(kp, iterations=2, memory_mib=64)
    kp.save()
    open_vault(path, "pw")  # must not raise


def test_production_refuses_weak_or_invalid_parameters(tmp_path: Path) -> None:
    kp = create_database(str(tmp_path / "vault.kdbx"), password="pw")
    with pytest.raises(ValueError):
        kdf.apply_kdf(kp, iterations=1, memory_mib=8)
    with pytest.raises(ValueError):
        kdf.apply_kdf(kp, iterations=0, memory_mib=64)
    with pytest.raises(ValueError):
        kdf.apply_kdf(kp, iterations=1, memory_mib=64, parallelism=0)


def test_calibration_returns_sane_iterations() -> None:
    iterations = kdf.calibrate_iterations(memory_mib=64)
    assert 1 <= iterations <= 100
