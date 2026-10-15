"""Vault session: create, open, edit, search, history ([S]).

Maps between the domain model and KDBX entries, and saves through storage.py
so every write is atomic, verified and backed up. The master password is held
only for the lifetime of the session (needed to verify saves by decrypting
them) and dropped on close().
"""

from __future__ import annotations

import hashlib
import hmac
import shutil
import struct
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pykeepass import PyKeePass, create_database
from pykeepass.exceptions import CredentialsError

from personal_vault.core import kdf, storage
from personal_vault.core.errors import InvalidPassword, VaultCorrupted, VaultError
from personal_vault.core.matching import host_and_port_of_url, match_urls
from personal_vault.core.models import LoginEntry, LoginSummary, SecretStr

LOGINS_GROUP = "Logins"
RECYCLE_BIN_GROUP = "Recycle Bin"
APP_GROUP = ".app"
MAX_HISTORY = 10
DEFAULT_KEEP_RECENT = 20
DEFAULT_KEEP_DAILY = 30
MATCH_SUBDOMAINS_KEY = "PM_MATCH_SUBDOMAINS"

_KDBX_SIG1 = b"\x03\xd9\xa2\x9a"
_KDBX_SIG2 = b"\x67\xfb\x4b\xb5"
_END_OF_HEADER = 0


def _verify_kdbx_header(data: bytes) -> None:
    """Reject a damaged header before pykeepass runs its KDF.

    pykeepass 4.2.0 derives the transformed key from the file's KDF parameters
    and only afterwards checks the header SHA-256, so one flipped byte in those
    parameters can make argon2 run effectively forever instead of raising. We
    verify the signature, version, field layout and the SHA-256 over the raw
    header ourselves first; every mismatch raises VaultCorrupted.
    """
    if data[:4] != _KDBX_SIG1 or data[4:8] != _KDBX_SIG2:
        raise VaultCorrupted("not a KDBX file")
    if data[8:12] != b"\x00\x00\x04\x00":  # minor 0, major 4 (KDBX 4)
        raise VaultCorrupted("unsupported KDBX version")
    pos = 12
    while True:
        if pos + 5 > len(data):
            raise VaultCorrupted("truncated KDBX header")
        field_id = data[pos]
        (size,) = struct.unpack_from("<I", data, pos + 1)
        pos += 5 + size
        if pos > len(data):
            raise VaultCorrupted("truncated KDBX header")
        if field_id == _END_OF_HEADER:
            break
    if pos + 64 > len(data):
        raise VaultCorrupted("truncated KDBX header")
    stored = data[pos : pos + 32]
    if not hmac.compare_digest(hashlib.sha256(data[:pos]).digest(), stored):
        raise VaultCorrupted("KDBX header checksum mismatch")


def open_vault(path: Path, password: str) -> PyKeePass:
    """Open and decrypt a vault, mapping failures to InvalidPassword/VaultCorrupted."""
    try:
        _verify_kdbx_header(path.read_bytes())
        return PyKeePass(str(path), password=password)
    except CredentialsError as exc:
        raise InvalidPassword("wrong master password") from exc
    except VaultCorrupted:
        raise
    except Exception as exc:
        # Damaged headers, payload checksum failures, truncation, XML errors:
        # all mean "cannot read this file safely". The cause stays out of the
        # user-facing message (AGENTS rule 3).
        raise VaultCorrupted("the vault file is damaged and could not be read") from exc


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _entry_urls(entry: Any) -> list[str]:
    urls: list[str] = []
    if entry.url:
        urls.append(entry.url)
    props = entry.custom_properties
    for key in sorted(k for k in props if k.startswith("KP2A_URL_")):
        value = props[key]
        if value:
            urls.append(value)
    return urls


def _entry_to_login(entry: Any) -> LoginEntry:
    return LoginEntry(
        id=entry.uuid,
        title=entry.title or "",
        username=entry.username or "",
        password=SecretStr(entry.password or ""),
        urls=_entry_urls(entry),
        notes=entry.notes or "",
        tags=list(entry.tags or []),
        match_subdomains=(entry.get_custom_property(MATCH_SUBDOMAINS_KEY) == "true"),
        created_at=_utc(entry.ctime),
        updated_at=_utc(entry.mtime),
    )


def _validate(login: LoginEntry) -> None:
    """Enforce the data-model field rules; messages never echo values."""
    if not 1 <= len(login.title) <= 200:
        raise ValueError("title must be 1-200 characters")
    if len(login.username) > 500:
        raise ValueError("username is too long (max 500 characters)")
    if len(login.password) > 4096:
        raise ValueError("password is too long (max 4096 characters)")
    if len(login.notes.encode("utf-8")) > 64 * 1024:
        raise ValueError("notes are too long (max 64 KiB)")
    if len(login.tags) > 20:
        raise ValueError("at most 20 tags")
    for url in login.urls:
        try:
            parts = urlsplit(url)
        except ValueError as exc:
            raise ValueError("urls must be http or https") from exc
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            raise ValueError("urls must be http or https")


def _apply_login(entry: Any, login: LoginEntry) -> None:
    entry.title = login.title
    entry.username = login.username
    entry.password = login.password.reveal()
    entry.url = login.urls[0] if login.urls else ""
    entry.notes = login.notes
    entry.tags = login.tags
    entry.set_custom_property(MATCH_SUBDOMAINS_KEY, "true" if login.match_subdomains else "false")
    for key in sorted(k for k in entry.custom_properties if k.startswith("KP2A_URL_")):
        entry.delete_custom_property(key)
    for index, url in enumerate(login.urls[1:], start=1):
        entry.set_custom_property(f"KP2A_URL_{index}", url)


class VaultSession:
    """One open vault, created or opened with a master password."""

    def __init__(
        self,
        kp: PyKeePass,
        path: Path,
        backups_dir: Path,
        password: str,
        keep_recent: int,
        keep_daily: int,
    ) -> None:
        self._kp: PyKeePass | None = kp
        self.path = Path(path)
        self.backups_dir = Path(backups_dir)
        self._password: str | None = password
        self._keep_recent = keep_recent
        self._keep_daily = keep_daily

    @property
    def _open_kp(self) -> PyKeePass:
        if self._kp is None:
            raise VaultError("vault is closed")
        return self._kp

    # --- lifecycle ---------------------------------------------------------

    @classmethod
    def create(
        cls,
        path: str | Path,
        password: str,
        backups_dir: str | Path,
        *,
        keep_recent: int = DEFAULT_KEEP_RECENT,
        keep_daily: int = DEFAULT_KEEP_DAILY,
    ) -> VaultSession:
        """Create a new vault with calibrated production KDF settings."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        iterations = kdf.calibrate_iterations()

        def writer(tmp: Path) -> None:
            kp = create_database(str(tmp), password=password)
            kdf.apply_kdf(kp, iterations=iterations)
            kp.add_group(kp.root_group, LOGINS_GROUP)
            kp.save()

        def verifier(tmp: Path) -> None:
            open_vault(tmp, password)

        storage.atomic_write(path, writer, verifier)
        return cls.open(path, password, backups_dir, keep_recent=keep_recent, keep_daily=keep_daily)

    @classmethod
    def open(
        cls,
        path: str | Path,
        password: str,
        backups_dir: str | Path,
        *,
        keep_recent: int = DEFAULT_KEEP_RECENT,
        keep_daily: int = DEFAULT_KEEP_DAILY,
    ) -> VaultSession:
        kp = open_vault(Path(path), password)
        return cls(
            kp,
            Path(path),
            Path(backups_dir),
            password,
            keep_recent=keep_recent,
            keep_daily=keep_daily,
        )

    def __enter__(self) -> VaultSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Drop the session; the vault stays as last saved."""
        self._kp = None
        self._password = None

    def save(self) -> None:
        """Atomically save with a backup, verifying the new file by decrypting it."""
        kp = self._open_kp
        password = self._password
        if password is None:
            raise VaultError("vault is closed")

        def writer(tmp: Path, kp: PyKeePass = kp) -> None:
            kp.save(str(tmp))

        def verifier(tmp: Path, password: str = password) -> None:
            open_vault(tmp, password)

        storage.save_with_backup(
            self.path,
            writer,
            verifier,
            self.backups_dir,
            self._keep_recent,
            self._keep_daily,
        )

    def export_kdbx(self, target: str | Path, new_password: str) -> None:
        """Write an encrypted copy of the vault to ``target`` under a new password.

        The copy is made from the last saved file (never from unsaved
        in-memory changes) and is verified by decrypting it with the new
        password before it replaces anything at ``target``.
        """
        password = self._password
        if password is None:
            raise VaultError("vault is closed")
        target = Path(target)
        if target.resolve() == self.path.resolve():
            raise ValueError("the export target must differ from the vault file")

        def writer(tmp: Path) -> None:
            kp = open_vault(self.path, password)
            kp.password = new_password
            kp.save(str(tmp))

        def verifier(tmp: Path) -> None:
            open_vault(tmp, new_password)

        storage.atomic_write(target, writer, verifier)

    def restore_backup(self, backup: str | Path) -> VaultSession:
        """Replace the vault with a backup copy and reopen it (same password).

        The backup must decrypt with the session's master password before
        anything is overwritten; the replacement itself is atomic.
        """
        password = self._password
        if password is None:
            raise VaultError("vault is closed")
        backup = Path(backup)
        open_vault(backup, password)  # refuse a bad backup before touching the vault

        def writer(tmp: Path) -> None:
            shutil.copyfile(backup, tmp)

        def verifier(tmp: Path) -> None:
            open_vault(tmp, password)

        storage.atomic_write(self.path, writer, verifier)
        return VaultSession.open(
            self.path,
            password,
            self.backups_dir,
            keep_recent=self._keep_recent,
            keep_daily=self._keep_daily,
        )

    # --- entries -----------------------------------------------------------

    def _logins_group(self) -> Any:
        kp = self._open_kp
        group = kp.find_groups(name=LOGINS_GROUP, first=True)
        if group is None:
            group = kp.add_group(kp.root_group, LOGINS_GROUP)
        return group

    def _find_anywhere(self, entry_id: uuid.UUID) -> Any:
        for group in self._open_kp.groups:
            for entry in group.entries:
                if entry.uuid == entry_id:
                    return entry
        raise KeyError(entry_id)

    def add(self, entry: LoginEntry) -> None:
        _validate(entry)
        new = self._open_kp.add_entry(
            self._logins_group(),
            title=entry.title,
            username=entry.username,
            password=entry.password.reveal(),
        )
        _apply_login(new, entry)
        new.uuid = entry.id
        new.ctime = entry.created_at
        new.mtime = entry.updated_at

    def edit(self, entry: LoginEntry) -> None:
        _validate(entry)
        current = self._find_anywhere(entry.id)
        if current.group is not None and current.group.name == RECYCLE_BIN_GROUP:
            raise ValueError("a deleted entry cannot be edited")
        current.save_history()
        _apply_login(current, entry)
        current.mtime = entry.updated_at
        while len(current.history) > MAX_HISTORY:
            current.delete_history(current.history[0])

    def delete(self, entry_id: uuid.UUID) -> None:
        entry = self._find_anywhere(entry_id)
        if entry.group is not None and entry.group.name == RECYCLE_BIN_GROUP:
            raise ValueError("entry is already in the Recycle Bin")
        self._open_kp.trash_entry(entry)

    def get(self, entry_id: uuid.UUID) -> LoginEntry:
        return _entry_to_login(self._find_anywhere(entry_id))

    def list_logins(self) -> list[LoginSummary]:
        summaries = [
            LoginSummary(
                id=entry.uuid,
                title=entry.title or "",
                username=entry.username or "",
                hosts=tuple(self._hosts(_entry_urls(entry))),
            )
            for entry in self._logins_group().entries
        ]
        return sorted(summaries, key=lambda s: s.title.lower())

    def matching_logins(self, page_url: str) -> list[LoginSummary]:
        """Logins whose URLs match the page under the site matching rules (I4)."""
        matches = []
        for entry in self._logins_group().entries:
            login = _entry_to_login(entry)
            if match_urls(login.urls, page_url, match_subdomains=login.match_subdomains):
                matches.append(
                    LoginSummary(
                        id=entry.uuid,
                        title=entry.title or "",
                        username=entry.username or "",
                        hosts=tuple(self._hosts(_entry_urls(entry))),
                    )
                )
        return sorted(matches, key=lambda s: s.title.lower())

    def search(self, query: str) -> list[LoginSummary]:
        needle = query.lower()
        results = []
        for entry in self._logins_group().entries:
            haystack = " ".join(
                [entry.title or "", entry.username or "", entry.notes or ""]
                + _entry_urls(entry)
                + list(entry.tags or [])
            ).lower()
            if needle in haystack:
                results.append(
                    LoginSummary(
                        id=entry.uuid,
                        title=entry.title or "",
                        username=entry.username or "",
                        hosts=tuple(self._hosts(_entry_urls(entry))),
                    )
                )
        return sorted(results, key=lambda s: s.title.lower())

    def history(self, entry_id: uuid.UUID) -> list[LoginEntry]:
        entry = self._find_anywhere(entry_id)
        return [_entry_to_login(item) for item in entry.history]

    # --- hidden .app group ---------------------------------------------------

    def _app_group(self) -> Any:
        kp = self._open_kp
        group = kp.find_groups(name=APP_GROUP, first=True)
        if group is None:
            group = kp.add_group(kp.root_group, APP_GROUP)
        return group

    def get_app_value(self, name: str) -> str | None:
        """Read a value the app stores for itself (pairing key, sync token)."""
        for entry in self._app_group().entries:
            if entry.title == name:
                return entry.password or None
        return None

    def set_app_value(self, name: str, value: str) -> None:
        """Store an app value in the hidden .app group; KeePassXC shows a note."""
        entry = next((e for e in self._app_group().entries if e.title == name), None)
        if entry is None:
            entry = self._open_kp.add_entry(
                self._app_group(), title=name, username="", password=value
            )
            entry.notes = "Managed by Personal Vault - do not edit"
        else:
            entry.password = value

    @staticmethod
    def _hosts(urls: list[str]) -> list[str]:
        hosts = []
        for url in urls:
            parsed = host_and_port_of_url(url)
            if parsed is not None:
                hosts.append(parsed[0])
        return hosts
