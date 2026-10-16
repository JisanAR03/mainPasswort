"""M2-08: export, import and backup restore without any UI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core.errors import InvalidPassword, VaultCorrupted
from personal_vault.core.transfer import (
    MAX_CSV_BYTES,
    MAX_KDBX_BYTES,
    export_csv,
    import_csv,
    import_kdbx,
)
from personal_vault.core.vault import VaultSession, open_vault

NEW_EXPORT_PASSWORD = "a-brand-new-password-123"


@pytest.fixture
def session(weak_session: VaultSession) -> VaultSession:
    session = weak_session
    session.add(make_login(title="GitHub", username="gh@example.com"))
    session.add(make_login(title="Mail", username="mail@example.com", notes="secret-note"))
    session.save()
    return session


def test_export_kdbx_opens_with_the_new_password(session: VaultSession, tmp_path: Path) -> None:
    target = tmp_path / "export.kdbx"
    session.export_kdbx(target, NEW_EXPORT_PASSWORD)
    kp = open_vault(target, NEW_EXPORT_PASSWORD)
    titles = {entry.title for entry in kp.entries}
    assert "GitHub" in titles and "Mail" in titles
    with pytest.raises(InvalidPassword):
        open_vault(target, WEAK_PASSWORD)  # the old password no longer works


def test_export_kdbx_refuses_the_vault_file_itself(session: VaultSession, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        session.export_kdbx(session.path, NEW_EXPORT_PASSWORD)


def test_export_kdbx_leaves_the_apps_own_secrets_behind(
    session: VaultSession, tmp_path: Path
) -> None:
    """An export goes to other people and other programs; this install's tokens do not.

    The hidden ``.app`` group holds the Drive refresh token and the pairing key.
    M6-03 found the KDBX export carrying them, because it was a copy of the file.
    """
    token = "CANARY-drive-refresh-token-3d21"
    session.set_app_value("drive-sync", token, username="owner@example.com")
    session.save()
    target = tmp_path / "export.kdbx"

    session.export_kdbx(target, NEW_EXPORT_PASSWORD)

    exported = open_vault(target, NEW_EXPORT_PASSWORD)
    assert {entry.title for entry in exported.entries} == {"GitHub", "Mail"}
    assert exported.find_groups(name=".app", first=True) is None
    # the vault the export was made from keeps its token
    assert session.get_app_value("drive-sync") == token


def test_export_csv_has_one_row_per_entry_and_no_other_data(
    session: VaultSession, tmp_path: Path
) -> None:
    target = tmp_path / "export.csv"
    export_csv(session, target)
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "title,username,password,urls"
    assert len(lines) == 3  # header + two entries
    assert "GitHub" in lines[1] and "gh@example.com" in lines[1]
    assert "secret-note" not in target.read_text(encoding="utf-8")  # notes never exported


def test_import_csv_lands_entries_in_a_new_group(session: VaultSession, tmp_path: Path) -> None:
    source = tmp_path / "import.csv"
    source.write_text(
        "title,username,password,urls\n"
        "Imported One,one@example.com,pass-one,https://one.example.com\n"
        "Imported Two,two@example.com,pass-two,https://two.example.com\n",
        encoding="utf-8",
    )
    count = import_csv(source, session)
    assert count == 2
    groups = [g.name for g in session._open_kp.groups if g.name.startswith("Imported ")]
    assert len(groups) == 1
    assert len(session._open_kp.find_groups(name=groups[0], first=True).entries) == 2


def test_import_csv_refuses_bad_files_never_crashing(session: VaultSession, tmp_path: Path) -> None:
    bad_header = tmp_path / "bad-header.csv"
    bad_header.write_text("a,b,c\nx,y,z\n", encoding="utf-8")
    with pytest.raises(ValueError):
        import_csv(bad_header, session)

    bad_rows = tmp_path / "bad-rows.csv"
    bad_rows.write_text("title,username,password,urls\nonly,three\n", encoding="utf-8")
    with pytest.raises(ValueError):
        import_csv(bad_rows, session)

    not_utf8 = tmp_path / "not-utf8.csv"
    not_utf8.write_bytes(b"\xff\xfe\x00\x01" * 10)
    with pytest.raises(ValueError):
        import_csv(not_utf8, session)

    invalid = tmp_path / "invalid.csv"
    invalid.write_text("title,username,password,urls\n,user,pass,https://e.com\n", encoding="utf-8")
    with pytest.raises(ValueError):
        import_csv(invalid, session)  # empty title fails the field rules

    huge = tmp_path / "huge.csv"
    huge.write_bytes(b"x" * (MAX_CSV_BYTES + 1))
    with pytest.raises(ValueError):
        import_csv(huge, session)


def test_import_kdbx_lands_entries_and_refuses_bad_input(
    session: VaultSession, tmp_path: Path
) -> None:
    source = tmp_path / "source.kdbx"
    build_weak_vault(source)
    with VaultSession.open(source, WEAK_PASSWORD, tmp_path / "src-backups") as other:
        other.add(make_login(title="From Elsewhere"))
        other.save()
    count = import_kdbx(source, WEAK_PASSWORD, session)
    assert count == 1
    groups = [g.name for g in session._open_kp.groups if g.name.startswith("Imported ")]
    assert len(groups) == 1

    with pytest.raises(InvalidPassword):
        import_kdbx(source, "not-the-password-123", session)

    fake = tmp_path / "fake.kdbx"
    fake.write_bytes(b"\x00" * (MAX_KDBX_BYTES + 1))
    with pytest.raises(ValueError):
        import_kdbx(fake, WEAK_PASSWORD, session)


def test_restore_backup_replaces_the_vault_and_reopens(
    tmp_path: Path,
) -> None:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    backups = tmp_path / "backups"
    with VaultSession.open(path, WEAK_PASSWORD, backups) as session:
        entry = make_login(title="Backed Up Entry")
        session.add(entry)
        session.save()  # backup #1: empty vault, #2 after save: has the entry

    with VaultSession.open(path, WEAK_PASSWORD, backups) as session:
        session.delete(entry.id)
        session.save()  # backup #3: without the entry
        assert session.list_logins() == []

        newest_backup = sorted(backups.glob("vault-*.kdbx"))[1]  # the state with the entry
        reopened = session.restore_backup(newest_backup)
        try:
            assert [s.title for s in reopened.list_logins()] == ["Backed Up Entry"]
        finally:
            reopened.close()
        assert session.list_logins() == []  # the old session is untouched


def test_restore_backup_refuses_a_bad_backup(tmp_path: Path) -> None:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    backups = tmp_path / "backups"
    with VaultSession.open(path, WEAK_PASSWORD, backups) as session:
        backups.mkdir(parents=True, exist_ok=True)
        corrupt = backups / "vault-20000101T000000Z-0001.kdbx"
        corrupt.write_bytes(b"not a vault")
        with pytest.raises(VaultCorrupted):
            session.restore_backup(corrupt)
        open_vault(path, WEAK_PASSWORD)  # the vault itself was left untouched


def test_transfer_writes_nothing_outside_the_chosen_paths(
    session: VaultSession, tmp_path: Path
) -> None:
    export_target = tmp_path / "chosen-export.kdbx"
    session.export_kdbx(export_target, NEW_EXPORT_PASSWORD)
    csv_target = tmp_path / "chosen-export.csv"
    export_csv(session, csv_target)
    source = tmp_path / "chosen-import.csv"
    source.write_text(
        "title,username,password,urls\nIn,user@example.com,pw,https://in.example.com\n",
        encoding="utf-8",
    )
    import_csv(source, session)
    session.save()

    names = {p.name for p in tmp_path.iterdir()}
    assert names == {
        "vault.kdbx",
        "backups",
        "chosen-export.kdbx",
        "chosen-export.csv",
        "chosen-import.csv",
    }
    assert not [p for p in tmp_path.rglob("*.tmp")]  # no atomic-write temp files remain
    for backup in (tmp_path / "backups").iterdir():
        assert backup.name.startswith("vault-")
