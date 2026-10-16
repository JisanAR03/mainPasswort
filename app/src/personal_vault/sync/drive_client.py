"""Everything sync needs from Google Drive, and nothing else ([S]: the token path).

The interface talks about whole vault files — never about what is inside one.
Two implementations exist: this real v3 REST client, and the in-memory
``FakeDrive`` the tests drive. Both satisfy ``DriveClient``, so the engine is
written once against the interface.

The access token arrives through a callable, so this class never holds a
refresh token and never refreshes anything itself: a 401 comes back as
``AuthExpired`` and the caller decides (sync.md: refresh once, then retry).
No call logs anything, so a token or a vault body cannot leak into a log line.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import requests

from personal_vault.sync.digests import md5_hex
from personal_vault.sync.errors import (
    AccessDenied,
    AuthExpired,
    NetworkError,
    RateLimited,
    RemoteMissing,
    RemoteUnreadable,
    ServerError,
    SyncError,
)

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_ABOUT_URL = "https://www.googleapis.com/drive/v3/about"
FOLDER_MIME = "application/vnd.google-apps.folder"
VAULT_SCHEMA = "1"

_FILE_FIELDS = (
    "id,name,md5Checksum,version,size,trashed,modifiedTime,headRevisionId,parents,appProperties"
)


@dataclass(frozen=True)
class RemoteFile:
    """A file on Drive, as the API reports it."""

    id: str
    name: str
    md5: str | None
    version: int | None
    head_revision_id: str | None
    trashed: bool = False
    size: int | None = None
    modified_time: str | None = None
    parent_id: str | None = None


@dataclass(frozen=True)
class Revision:
    """One entry of a file's history. Drive returns them newest first."""

    id: str
    modified_time: str | None = None


@runtime_checkable
class DriveClient(Protocol):
    """What the engine is allowed to ask Drive."""

    def find_vault_file(self, profile_id: str) -> RemoteFile | None: ...

    def ensure_folder(self, name: str, parent_id: str | None = None) -> str: ...

    def upload(
        self,
        *,
        file_id: str | None,
        name: str,
        parent_id: str,
        data: bytes,
        profile_id: str,
    ) -> RemoteFile: ...

    def metadata(self, file_id: str) -> RemoteFile: ...

    def download(self, file_id: str, *, expect_md5: str | None = None) -> bytes: ...

    def download_revision(
        self, file_id: str, revision_id: str, *, expect_md5: str | None = None
    ) -> bytes: ...

    def list_revisions(self, file_id: str) -> list[Revision]: ...


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _escape(value: str) -> str:
    """Drive's query language quotes with backslash-escaped single quotes."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _remote_file(item: Mapping[str, Any]) -> RemoteFile:
    parents = item.get("parents")
    return RemoteFile(
        id=str(item["id"]),
        name=str(item.get("name") or "vault.kdbx"),
        md5=_text(item.get("md5Checksum")),
        version=_number(item.get("version")),
        head_revision_id=_text(item.get("headRevisionId")),
        trashed=item.get("trashed") is True,
        size=_number(item.get("size")),
        modified_time=_text(item.get("modifiedTime")),
        parent_id=next((str(p) for p in parents), None) if isinstance(parents, list) else None,
    )


class HttpDriveClient:
    """The real client. One instance per profile, used from the sync worker."""

    def __init__(
        self,
        token: Callable[[], str],
        *,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._session = session if session is not None else requests.Session()
        self._timeout = timeout

    # -- files -----------------------------------------------------------

    def find_vault_file(self, profile_id: str) -> RemoteFile | None:
        """By ``appProperties``, never by name; trashed files count as found."""
        match = f"appProperties has {{ key='pm_profile_id' and value='{_escape(profile_id)}' }}"
        for trashed in ("false", "true"):
            found = self._list(f"{match} and trashed = {trashed}")
            if found:
                return _remote_file(found[0])
        return None

    def ensure_folder(self, name: str, parent_id: str | None = None) -> str:
        query = [f"name = '{_escape(name)}'", f"mimeType = '{FOLDER_MIME}'", "trashed = false"]
        if parent_id:
            query.append(f"'{_escape(parent_id)}' in parents")
        found = self._list(" and ".join(query))
        if found:
            return str(found[0]["id"])
        body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME}
        if parent_id:
            body["parents"] = [parent_id]
        reply = self._request("POST", DRIVE_FILES_URL, params={"fields": "id"}, json=body).json()
        return str(reply["id"])

    def upload(
        self,
        *,
        file_id: str | None,
        name: str,
        parent_id: str,
        data: bytes,
        profile_id: str,
    ) -> RemoteFile:
        """Send exactly these bytes, as a new file or a new version of one."""
        metadata: dict[str, Any] = {
            "name": name,
            "appProperties": {"pm_profile_id": profile_id, "pm_schema": VAULT_SCHEMA},
        }
        if file_id is None:
            method, url = "POST", DRIVE_UPLOAD_URL
            metadata["parents"] = [parent_id]
        else:
            method, url = "PATCH", f"{DRIVE_UPLOAD_URL}/{file_id}"
        reply = self._request(
            method,
            url,
            params={"uploadType": "multipart", "fields": _FILE_FIELDS},
            files={
                "metadata": (None, json.dumps(metadata).encode("utf-8"), "application/json"),
                "file": (name, data, "application/octet-stream"),
            },
        ).json()
        return _remote_file(reply)

    def account_email(self) -> str | None:
        """Whose Drive this is, for the "Connected as ..." line.

        Not part of the sync interface: the sign-in flow calls it once, with a
        freshly minted token, and only to label the connection.
        """
        reply = self._request(
            "GET", f"{DRIVE_ABOUT_URL}", params={"fields": "user(emailAddress)"}
        ).json()
        user = reply.get("user")
        return _text(user.get("emailAddress")) if isinstance(user, Mapping) else None

    def metadata(self, file_id: str) -> RemoteFile:
        """A 404 is ``RemoteMissing``: the file we synced against is gone."""
        reply = self._request(
            "GET", f"{DRIVE_FILES_URL}/{file_id}", params={"fields": _FILE_FIELDS}
        ).json()
        return _remote_file(reply)

    # -- bytes -----------------------------------------------------------

    def download(self, file_id: str, *, expect_md5: str | None = None) -> bytes:
        return self._media(f"{DRIVE_FILES_URL}/{file_id}", expect_md5)

    def download_revision(
        self, file_id: str, revision_id: str, *, expect_md5: str | None = None
    ) -> bytes:
        return self._media(f"{DRIVE_FILES_URL}/{file_id}/revisions/{revision_id}", expect_md5)

    def list_revisions(self, file_id: str) -> list[Revision]:
        reply = self._request(
            "GET",
            f"{DRIVE_FILES_URL}/{file_id}/revisions",
            params={"fields": "revisions(id,modifiedTime)", "pageSize": 100},
        ).json()
        items = reply.get("revisions")
        return (
            [
                Revision(id=str(item["id"]), modified_time=_text(item.get("modifiedTime")))
                for item in items
            ]
            if isinstance(items, list)
            else []
        )

    # -- the one place that speaks HTTP ----------------------------------

    def _list(self, query: str) -> list[Mapping[str, Any]]:
        reply = self._request(
            "GET",
            DRIVE_FILES_URL,
            params={
                "q": query,
                "fields": f"files({_FILE_FIELDS})",
                "spaces": "drive",
                "pageSize": 10,
            },
        ).json()
        files = reply.get("files")
        return (
            [item for item in files if isinstance(item, Mapping)] if isinstance(files, list) else []
        )

    def _media(self, url: str, expect_md5: str | None) -> bytes:
        content = self._request("GET", url, params={"alt": "media"}).content
        if expect_md5 is not None and md5_hex(content) != expect_md5:
            raise RemoteUnreadable("Drive handed back bytes that do not match its own checksum")
        return content

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        headers = {"Authorization": f"Bearer {self._token()}"}
        try:
            reply = self._session.request(
                method, url, headers=headers, timeout=self._timeout, **kwargs
            )
        except requests.Timeout as exc:
            raise NetworkError("Drive did not answer in time") from exc
        except requests.RequestException as exc:
            raise NetworkError("Drive is unreachable") from exc
        status = reply.status_code
        if status == 401:
            raise AuthExpired("the access token was refused")
        if status == 403:
            raise AccessDenied("Drive refused the request")
        if status == 404:
            raise RemoteMissing("the file is no longer on Drive")
        if status == 429:
            raise RateLimited("Drive is rate limiting us")
        if status >= 500:
            raise ServerError("Drive had a server error")
        if status >= 400:
            raise SyncError(f"Drive refused the request ({status})")
        return reply
