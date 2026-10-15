"""Export and import without any UI (M2-08).

Everything imported (KDBX or CSV) is parsed as untrusted input: size limits
apply before parsing, every row/entry is validated with the data-model field
rules, and a bad file raises ValueError with a message - never a crash.
Imported entries land in a new group under the root (named "Imported <UTC
timestamp>") for review; nothing here merges them into Logins.

Size limits are a documented choice (the spec leaves the numbers open):
16 MiB for KDBX files and 1 MiB for CSV files.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

from personal_vault.core.models import LoginEntry, SecretStr
from personal_vault.core.vault import (
    RECYCLE_BIN_GROUP,
    VaultSession,
    _apply_login,
    _entry_to_login,
    _validate,
    open_vault,
)

MAX_KDBX_BYTES = 16 * 1024 * 1024
MAX_CSV_BYTES = 1 * 1024 * 1024
CSV_FIELDS = ("title", "username", "password", "urls")


def _import_group_name() -> str:
    return f"Imported {datetime.now(UTC):%Y-%m-%d %H:%M} UTC"


def _check_size(path: Path, limit: int, label: str) -> None:
    if path.stat().st_size > limit:
        raise ValueError(f"the {label} file is larger than {limit // (1024 * 1024)} MiB")


def export_csv(session: VaultSession, target: str | Path) -> None:
    """Write one row per login entry: title, username, password, urls.

    Notes, tags and metadata are deliberately not exported; only the login
    fields that another password manager can import (data-model.md).
    """
    rows = [_entry_to_login(entry) for entry in session._logins_group().entries]
    with Path(target).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_FIELDS)
        for login in rows:
            writer.writerow(
                [
                    login.title,
                    login.username,
                    login.password.reveal(),
                    "\n".join(login.urls),
                ]
            )


def import_csv(source: str | Path, session: VaultSession) -> int:
    """Parse a CSV file as untrusted input; entries land in a new group."""
    source = Path(source)
    _check_size(source, MAX_CSV_BYTES, "CSV")
    try:
        text = source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("the CSV file is not valid UTF-8 text") from exc
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise ValueError("the CSV file is malformed and could not be read") from exc
    if not rows or tuple(rows[0]) != CSV_FIELDS:
        raise ValueError("the CSV file must start with a title,username,password,urls header")
    if any(len(row) != len(CSV_FIELDS) for row in rows[1:]):
        raise ValueError("every CSV row must have title,username,password,urls columns")
    logins: list[LoginEntry] = []
    for title, username, password, urls in rows[1:]:
        logins.append(
            LoginEntry(
                id=uuid.uuid4(),
                title=title,
                username=username,
                password=SecretStr(password),
                urls=[line.strip() for line in urls.split("\n") if line.strip()],
                notes="",
                tags=[],
                match_subdomains=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
    for login in logins:
        _validate(login)
    return _import_entries(session, logins)


def import_kdbx(source: str | Path, password: str, session: VaultSession) -> int:
    """Open a KDBX file as untrusted input; entries land in a new group."""
    source = Path(source)
    _check_size(source, MAX_KDBX_BYTES, "KDBX")
    kp = open_vault(source, password)  # maps failures to InvalidPassword/VaultCorrupted
    logins = []
    for group in kp.groups:
        if group.name == RECYCLE_BIN_GROUP:
            continue
        for entry in group.entries:
            login = _entry_to_login(entry)
            _validate(login)
            logins.append(login)
    return _import_entries(session, logins)


def _import_entries(session: VaultSession, logins: list[LoginEntry]) -> int:
    """Add validated entries to a new group under the root, for review."""
    if not logins:
        return 0
    group = session._open_kp.add_group(session._open_kp.root_group, _import_group_name())
    for login in logins:
        new = session._open_kp.add_entry(
            group,
            title=login.title,
            username=login.username,
            password=login.password.reveal(),
        )
        _apply_login(new, login)
        new.uuid = login.id
        new.ctime = login.created_at
        new.mtime = login.updated_at
    return len(logins)
