"""M1-04: vault CRUD, search, history, save semantics and error mapping ([S])."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core import kdf
from personal_vault.core.errors import InvalidPassword, VaultCorrupted
from personal_vault.core.vault import VaultSession, open_vault

pytestmark = pytest.mark.integration


def test_create_and_reopen_with_production_settings(tmp_path: Path) -> None:
    path = tmp_path / "new" / "vault.kdbx"
    with VaultSession.create(path, WEAK_PASSWORD, tmp_path / "backups") as session:
        assert session.list_logins() == []
    opened = open_vault(path, WEAK_PASSWORD)  # reopens with the calibrated KDF
    params = opened.kdbx.header.value.dynamic_header.kdf_parameters.data.dict
    assert bytes(params[kdf.UUID_KEY].value) == kdf.KDF_UUID_ARGON2ID
    assert int(params[kdf.MEMORY_KEY].value) == 128 * 1024 * 1024
    assert int(params[kdf.PARALLELISM_KEY].value) == 2
    assert int(params[kdf.ITERATIONS_KEY].value) >= 1


def test_add_get_round_trip(weak_session: VaultSession) -> None:
    entry = make_login(
        urls=["https://example.com", "https://docs.example.com"],
        match_subdomains=True,
        tags=["work", "important"],
    )
    weak_session.add(entry)
    weak_session.save()
    got = weak_session.get(entry.id)
    assert got.title == entry.title
    assert got.username == entry.username
    assert got.password == entry.password
    assert got.urls == entry.urls
    assert got.match_subdomains is True
    assert got.tags == entry.tags


def test_edit_creates_history_capped_at_ten(weak_session: VaultSession) -> None:
    entry = make_login()
    weak_session.add(entry)
    weak_session.save()
    for index in range(12):
        edited = weak_session.get(entry.id)
        edited.title = f"Edit {index}"
        edited.updated_at = datetime.now(UTC)
        weak_session.edit(edited)
        weak_session.save()
    history = weak_session.history(entry.id)
    assert len(history) == 10
    # The oldest two snapshots (the original and "Edit 0") were trimmed.
    assert [item.title for item in history] == [f"Edit {i}" for i in range(1, 11)]


def test_delete_moves_to_recycle_bin(weak_session: VaultSession) -> None:
    entry = make_login()
    weak_session.add(entry)
    weak_session.save()
    weak_session.delete(entry.id)
    weak_session.save()
    assert entry.id not in [s.id for s in weak_session.list_logins()]
    assert weak_session.get(entry.id).title == entry.title  # still reachable
    with pytest.raises(ValueError):
        weak_session.delete(entry.id)
    with pytest.raises(ValueError):
        weak_session.edit(weak_session.get(entry.id))


def test_search_matches_title_username_notes(weak_session: VaultSession) -> None:
    weak_session.add(make_login(title="GitHub", username="gh@example.com", notes="work"))
    weak_session.add(make_login(title="Mail", username="mail@example.com", notes="personal"))
    weak_session.save()
    assert {s.title for s in weak_session.search("github")} == {"GitHub"}
    assert {s.title for s in weak_session.search("mail@example.com")} == {"Mail"}
    assert {s.title for s in weak_session.search("personal")} == {"Mail"}
    assert weak_session.search("no-such-needle") == []


def test_sessions_are_isolated(tmp_path: Path) -> None:
    other_password = "another-master-password"
    first_path = build_weak_vault(tmp_path / "a" / "vault.kdbx")
    second_path = build_weak_vault(tmp_path / "b" / "vault.kdbx", password=other_password)
    with (
        VaultSession.open(first_path, WEAK_PASSWORD, tmp_path / "backups-a") as first,
        VaultSession.open(second_path, other_password, tmp_path / "backups-b") as second,
    ):
        first.add(make_login(title="In A"))
        first.save()
        assert [s.title for s in second.list_logins()] == []
    # Neither profile's password opens the other's vault.
    with pytest.raises(InvalidPassword):
        open_vault(first_path, other_password)
    with pytest.raises(InvalidPassword):
        open_vault(second_path, WEAK_PASSWORD)


def test_wrong_password_maps_to_invalid_password(weak_vault_path: Path) -> None:
    with pytest.raises(InvalidPassword):
        open_vault(weak_vault_path, "not-the-password")


def test_failed_open_leaves_bytes_identical(weak_vault_path: Path) -> None:
    before = weak_vault_path.read_bytes()
    with pytest.raises(InvalidPassword):
        open_vault(weak_vault_path, "not-the-password")
    assert weak_vault_path.read_bytes() == before


def test_corrupted_file_maps_to_vault_corrupted(weak_vault_path: Path) -> None:
    corrupt = weak_vault_path.with_name("corrupt.kdbx")
    data = bytearray(weak_vault_path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    corrupt.write_bytes(data)
    with pytest.raises(VaultCorrupted):
        open_vault(corrupt, WEAK_PASSWORD)


def test_save_writes_backup_and_reopens(tmp_path: Path) -> None:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    with VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups") as session:
        session.add(make_login(title="Backed up"))
        session.save()
    backups = list((tmp_path / "backups").glob("vault-*.kdbx"))
    assert len(backups) == 1
    fresh = VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups")
    assert [s.title for s in fresh.list_logins()] == ["Backed up"]


def test_validation_enforces_data_model_limits(weak_session: VaultSession) -> None:
    with pytest.raises(ValueError):
        weak_session.add(make_login(title=""))
    with pytest.raises(ValueError):
        weak_session.add(make_login(username="x" * 501))
    with pytest.raises(ValueError):
        weak_session.add(make_login(urls=["ftp://example.com"]))
    with pytest.raises(ValueError):
        weak_session.add(make_login(tags=[f"t{i}" for i in range(21)]))


@pytest.mark.skipif(
    not (os.environ.get("KEEPASSXC_CLI") or shutil.which("keepassxc-cli")),
    reason="keepassxc-cli not installed",
)
def test_keepassxc_cli_can_open_our_vault(tmp_path: Path) -> None:
    # The production create path (Argon2id, 128 MiB, calibrated iterations),
    # then KeePassXC reads the result back.
    path = tmp_path / "vault.kdbx"
    with VaultSession.create(path, WEAK_PASSWORD, tmp_path / "backups") as session:
        session.add(make_login(title="GitHub"))
        session.save()
    cli = os.environ.get("KEEPASSXC_CLI") or shutil.which("keepassxc-cli")
    result = subprocess.run(
        [cli, "ls", "-R", str(path)],
        input=f"{WEAK_PASSWORD}\n",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "GitHub" in result.stdout
