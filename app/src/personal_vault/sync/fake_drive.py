"""An in-memory Drive, for the engine's tests. Same interface, no network.

Beyond behaving like Drive, it can be made to misbehave on demand — go
offline, return a 429 or a 5xx, hand back corrupted bytes — and another device
can write to the same file between any two calls, which is how the race in
sync.md ("closing the race window") is tested.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from personal_vault.sync.digests import md5_hex
from personal_vault.sync.drive_client import VAULT_SCHEMA, RemoteFile, Revision
from personal_vault.sync.errors import NetworkError, RemoteMissing, RemoteUnreadable, SyncError


@dataclass
class _Snapshot:
    """One revision: Drive keeps the bytes each version had."""

    id: str
    content: bytes
    modified_time: str


@dataclass
class _File:
    id: str
    name: str
    content: bytes
    app_properties: dict[str, str]
    version: int = 1
    trashed: bool = False
    parent_id: str | None = None
    revisions: list[_Snapshot] = field(default_factory=list)

    def snapshot(self) -> None:
        self.revisions.insert(0, _Snapshot(self.revision_id(), self.content, _stamp()))

    def revision_id(self) -> str:
        return f"rev-{self.id}-{self.version}"


def _stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class FakeDrive:
    """Implements ``DriveClient``; tests drive it, the engine never sees it."""

    def __init__(self) -> None:
        self.files: dict[str, _File] = {}
        self.folders: dict[str, str] = {}
        self.calls: list[str] = []
        # failure injection
        self.offline = False
        self.corrupt_downloads = False
        self.failures: list[SyncError] = []  # raised one per call, in order
        self.before: dict[str, Callable[[FakeDrive], None]] = {}  # one-shot, by call name
        self._next_id = 0

    # -- what the tests do to it -----------------------------------------

    def write_from_another_device(
        self,
        content: bytes,
        *,
        profile_id: str,
        name: str = "vault.kdbx",
        trashed: bool = False,
    ) -> str:
        """Another laptop saving the same profile: create the file or replace it."""
        existing = self._for_profile(profile_id)
        if existing is None:
            self._next_id += 1
            file = _File(
                id=f"file-{self._next_id}",
                name=name,
                content=content,
                app_properties={"pm_profile_id": profile_id, "pm_schema": VAULT_SCHEMA},
                parent_id=self.folders.get("root/PersonalVault"),
                trashed=trashed,
            )
            self.files[file.id] = file
            file.snapshot()
            return file.id
        existing.content = content
        existing.version += 1
        existing.trashed = trashed
        existing.snapshot()
        return existing.id

    def trash(self, file_id: str) -> None:
        self.files[file_id].trashed = True

    def stored_bytes(self, file_id: str) -> bytes:
        return self.files[file_id].content

    # -- the interface ---------------------------------------------------

    def find_vault_file(self, profile_id: str) -> RemoteFile | None:
        self._call("find_vault_file")
        found = self._for_profile(profile_id, trashed=False) or self._for_profile(
            profile_id, trashed=True
        )
        return self._remote_file(found) if found is not None else None

    def ensure_folder(self, name: str, parent_id: str | None = None) -> str:
        self._call("ensure_folder")
        key = f"{parent_id or 'root'}/{name}"
        if key not in self.folders:
            self._next_id += 1
            self.folders[key] = f"folder-{self._next_id}"
        return self.folders[key]

    def upload(
        self,
        *,
        file_id: str | None,
        name: str,
        parent_id: str,
        data: bytes,
        profile_id: str,
    ) -> RemoteFile:
        self._call("upload")
        if file_id is None:
            self._next_id += 1
            file = _File(
                id=f"file-{self._next_id}",
                name=name,
                content=data,
                app_properties={"pm_profile_id": profile_id, "pm_schema": VAULT_SCHEMA},
                parent_id=parent_id,
            )
            self.files[file.id] = file
        else:
            file = self._get(file_id)
            file.name = name
            file.content = data
            file.app_properties = {"pm_profile_id": profile_id, "pm_schema": VAULT_SCHEMA}
            file.version += 1
        file.snapshot()
        return self._remote_file(file)

    def metadata(self, file_id: str) -> RemoteFile:
        self._call("metadata")
        return self._remote_file(self._get(file_id))

    def download(self, file_id: str, *, expect_md5: str | None = None) -> bytes:
        self._call("download")
        return self._verified(self._get(file_id).content, expect_md5)

    def download_revision(
        self, file_id: str, revision_id: str, *, expect_md5: str | None = None
    ) -> bytes:
        self._call("download_revision")
        file = self._get(file_id)
        for snapshot in file.revisions:
            if snapshot.id == revision_id:
                return self._verified(snapshot.content, expect_md5)
        raise RemoteMissing(f"revision {revision_id} is no longer on Drive")

    def list_revisions(self, file_id: str) -> list[Revision]:
        self._call("list_revisions")
        return [
            Revision(id=snapshot.id, modified_time=snapshot.modified_time)
            for snapshot in self._get(file_id).revisions
        ]

    # -- internals -------------------------------------------------------

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.offline:
            raise NetworkError("the fake Drive is offline")
        hook = self.before.pop(name, None)
        if hook is not None:
            hook(self)
        if self.failures:
            raise self.failures.pop(0)

    def _get(self, file_id: str) -> _File:
        try:
            return self.files[file_id]
        except KeyError as exc:
            raise RemoteMissing(f"{file_id} is not on the fake Drive") from exc

    def _for_profile(self, profile_id: str, *, trashed: bool | None = None) -> _File | None:
        for file in self.files.values():
            if file.app_properties.get("pm_profile_id") != profile_id:
                continue
            if trashed is None or file.trashed is trashed:
                return file
        return None

    def _verified(self, content: bytes, expect_md5: str | None) -> bytes:
        if self.corrupt_downloads:
            content = content + b"corrupted-in-transit"
        if expect_md5 is not None and md5_hex(content) != expect_md5:
            raise RemoteUnreadable("Drive handed back bytes that do not match its own checksum")
        return content

    def _remote_file(self, file: _File) -> RemoteFile:
        return RemoteFile(
            id=file.id,
            name=file.name,
            md5=md5_hex(file.content),
            version=file.version,
            head_revision_id=file.revision_id(),
            trashed=file.trashed,
            size=len(file.content),
            modified_time=_stamp(),
            parent_id=file.parent_id,
        )
