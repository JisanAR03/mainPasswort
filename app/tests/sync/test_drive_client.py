"""M5-02: one interface, two implementations: the Drive v3 client and the fake.

The real client runs against a stub `requests.Session` that behaves like the
handful of Drive endpoints we use, so the tests can see the URLs, the bearer
token and the exact bytes without a network.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Any

import pytest
import requests
from personal_vault.sync.digests import md5_hex
from personal_vault.sync.drive_client import (
    DRIVE_FILES_URL,
    DRIVE_UPLOAD_URL,
    FOLDER_MIME,
    DriveClient,
    HttpDriveClient,
    RemoteFile,
)
from personal_vault.sync.errors import (
    AccessDenied,
    AuthExpired,
    NetworkError,
    RateLimited,
    RemoteMissing,
    RemoteUnreadable,
    ServerError,
)
from personal_vault.sync.fake_drive import FakeDrive

pytestmark = pytest.mark.sync

TOKEN = "ya29.super-secret-access-token"
PROFILE = "9f2c1d3e4b5a69788796a5b4c3d2e1f0"
VAULT = b"kdbx-bytes-one"
OTHERS = b"kdbx-bytes-from-the-other-laptop"
MODIFIED = "2026-10-16T09:00:00.000Z"

# --------------------------------------------------------------------------
# A stand-in for requests.Session, with just enough Drive in it
# --------------------------------------------------------------------------


class _Reply:
    def __init__(
        self, status: int, payload: dict[str, Any] | None = None, content: bytes = b""
    ) -> None:
        self.status_code = status
        self._payload = payload
        self.content = content

    def json(self) -> dict[str, Any]:
        assert self._payload is not None, "this reply has no JSON body"
        return self._payload


def _record(content: bytes, revision_id: str, version: int) -> dict[str, Any]:
    return {
        "id": revision_id,
        "modifiedTime": MODIFIED,
        "version": version,
        "content": content,
    }


class StubSession:
    """Behaves like Drive for list/get/upload/revisions; records every request."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.files: dict[str, dict[str, Any]] = {}
        self.status = 200  # set to make the next reply an error
        self.raise_: Exception | None = None  # set to make the next call blow up
        self._next_id = 0

    # -- what the tests set up and look at ------------------------------

    def write_from_another_device(
        self,
        content: bytes,
        *,
        profile_id: str = PROFILE,
        name: str = "vault.kdbx",
        trashed: bool = False,
    ) -> str:
        """Another device saving to the same Drive: creates the file or replaces it."""
        for file_id, entry in self.files.items():
            if (
                entry.get("appProperties", {}).get("pm_profile_id") == profile_id
                and entry.get("mimeType") != FOLDER_MIME
            ):
                self._store(file_id, content, name=name)
                entry["trashed"] = trashed
                return file_id
        return self._create(content, profile_id=profile_id, name=name, trashed=trashed)

    def stored_bytes(self, file_id: str) -> bytes:
        return self.files[file_id]["content"]  # type: ignore[no-any-return]

    def trash(self, file_id: str) -> None:
        self.files[file_id]["trashed"] = True

    # -- the Drive the client talks to ----------------------------------

    def _create(self, content: bytes, *, profile_id: str, name: str, trashed: bool = False) -> str:
        self._next_id += 1
        file_id = f"file-{self._next_id}"
        self.files[file_id] = dict(
            id=file_id,
            name=name,
            md5Checksum=md5_hex(content),
            version=1,
            size=str(len(content)),
            trashed=trashed,
            modifiedTime=MODIFIED,
            headRevisionId=f"rev-{file_id}-1",
            parents=[],
            appProperties={"pm_profile_id": profile_id, "pm_schema": "1"},
            content=content,
            revisions=[_record(content, f"rev-{file_id}-1", 1)],
        )
        return file_id

    def _store(self, file_id: str, content: bytes, *, name: str | None = None) -> None:
        entry = self.files[file_id]
        version = int(entry.get("version", 0)) + 1
        if name is not None:
            entry["name"] = name
        entry["content"] = content
        entry["md5Checksum"] = md5_hex(content)
        entry["size"] = str(len(content))
        entry["version"] = version
        entry["headRevisionId"] = f"rev-{file_id}-{version}"
        entry["modifiedTime"] = MODIFIED
        entry["revisions"].insert(0, _record(content, entry["headRevisionId"], version))

    def _public(self, file_id: str) -> dict[str, Any]:
        return {k: v for k, v in self.files[file_id].items() if k not in {"content", "revisions"}}

    def _matching(self, query: str) -> list[str]:
        name = re.search(r"name = '([^']*)'", query)
        profile = re.search(r"value='([^']*)'", query)
        trashed = re.search(r"trashed = (true|false)", query)
        folder = FOLDER_MIME in query
        parent = re.search(r"'([^']*)' in parents", query)
        found = []
        for file_id, entry in self.files.items():
            if folder and entry.get("mimeType") != FOLDER_MIME:
                continue
            if not folder and entry.get("mimeType") == FOLDER_MIME:
                continue
            if name and entry.get("name") != name.group(1):
                continue
            if profile and entry.get("appProperties", {}).get("pm_profile_id") != profile.group(1):
                continue
            if trashed and bool(entry.get("trashed", False)) is not (trashed.group(1) == "true"):
                continue
            if parent and parent.group(1) not in entry.get("parents", []):
                continue
            found.append(file_id)
        return found

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,  # noqa: A002 - the requests keyword
        files: dict[str, Any] | None = None,
    ) -> _Reply:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "timeout": timeout,
                "params": dict(params or {}),
                "json": json,
                "files": files,
            }
        )
        if self.raise_ is not None:
            raise self.raise_
        if self.status != 200:
            return _Reply(self.status)
        return self._dispatch(method, url, params or {}, json, files)

    def _dispatch(
        self,
        method: str,
        url: str,
        params: dict[str, Any],
        payload: dict[str, Any] | None,
        files: dict[str, Any] | None,
    ) -> _Reply:
        if url == DRIVE_FILES_URL and method == "GET":
            return _Reply(
                200, {"files": [self._public(f) for f in self._matching(str(params["q"]))]}
            )
        if url == DRIVE_FILES_URL and method == "POST":
            self._next_id += 1
            file_id = f"folder-{self._next_id}"
            assert payload is not None
            self.files[file_id] = {**payload, "id": file_id, "trashed": False}
            return _Reply(200, {"id": file_id})
        if url.startswith(DRIVE_UPLOAD_URL):
            assert files is not None
            metadata = json.loads(files["metadata"][1])
            content = files["file"][1]
            if method == "PATCH":
                file_id = url.rsplit("/", 1)[-1]
                self._store(file_id, content, name=metadata.get("name"))
                self.files[file_id].update(metadata)
            else:
                file_id = self._create(
                    content,
                    profile_id=metadata["appProperties"]["pm_profile_id"],
                    name=metadata["name"],
                )
                self.files[file_id].update(metadata)
            return _Reply(200, self._public(file_id))
        if url.startswith(DRIVE_FILES_URL):  # get metadata / get media / revisions
            parts = url[len(DRIVE_FILES_URL) + 1 :].split("/")
            file_id = parts[0]
            if file_id not in self.files:
                return _Reply(404)
            if len(parts) == 2 and parts[1] == "revisions":
                return _Reply(200, {"revisions": self.files[file_id]["revisions"]})
            if params.get("alt") == "media":
                if len(parts) == 3:  # one revision's bytes, as Drive keeps them
                    for record in self.files[file_id]["revisions"]:
                        if record["id"] == parts[2]:
                            return _Reply(200, content=record["content"])
                    return _Reply(404)
                return _Reply(200, content=self.files[file_id]["content"])
            return _Reply(200, self._public(file_id))
        raise AssertionError(f"the client called a URL we do not serve: {url}")


# --------------------------------------------------------------------------
# Both implementations, behind the same tests
# --------------------------------------------------------------------------


class RealDrive:
    """The real client, over the stub session."""

    def __init__(self) -> None:
        self.session = StubSession()
        self.client = HttpDriveClient(token=lambda: TOKEN, session=self.session)

    def write_from_another_device(self, content: bytes, **kwargs: Any) -> str:
        return self.session.write_from_another_device(content, **kwargs)

    def stored_bytes(self, file_id: str) -> bytes:
        return self.session.stored_bytes(file_id)

    def trash(self, file_id: str) -> None:
        self.session.trash(file_id)


class FakeDriveUnderTest:
    """The fake, presented like the real client's harness (and reachable for injection)."""

    def __init__(self) -> None:
        self.fake = FakeDrive()
        self.client = self.fake

    def write_from_another_device(self, content: bytes, **kwargs: Any) -> str:
        return self.fake.write_from_another_device(content, **kwargs)

    def stored_bytes(self, file_id: str) -> bytes:
        return self.fake.stored_bytes(file_id)

    def trash(self, file_id: str) -> None:
        self.fake.trash(file_id)


@pytest.fixture(params=["real", "fake"])
def drive(request: pytest.FixtureRequest) -> Iterator[Any]:
    """Every shared behaviour test runs against both implementations."""
    yield RealDrive() if request.param == "real" else FakeDriveUnderTest()


def _upload(drive: Any, data: bytes = VAULT, file_id: str | None = None) -> RemoteFile:
    folder = drive.client.ensure_folder("PersonalVault")
    return drive.client.upload(
        file_id=file_id, name="vault.kdbx", parent_id=folder, data=data, profile_id=PROFILE
    )


# --- the shared behaviour --------------------------------------------------


def test_a_profile_with_no_file_yet(drive: Any) -> None:
    assert drive.client.find_vault_file(PROFILE) is None


def test_the_file_is_found_by_app_properties_not_by_name(drive: Any) -> None:
    # another device named it differently: the name is not the identity
    file_id = drive.write_from_another_device(
        OTHERS, profile_id=PROFILE, name="work-vault-2026.kdbx"
    )
    found = drive.client.find_vault_file(PROFILE)
    assert found is not None
    assert found.id == file_id
    assert found.name == "work-vault-2026.kdbx"


def test_a_trashed_file_is_there_but_trashed(drive: Any) -> None:
    file_id = drive.write_from_another_device(OTHERS, profile_id=PROFILE, trashed=True)
    found = drive.client.find_vault_file(PROFILE)
    assert found is not None
    assert found.id == file_id
    assert found.trashed is True


def test_a_file_of_another_profile_is_not_ours(drive: Any) -> None:
    drive.write_from_another_device(OTHERS, profile_id="someone-else")
    assert drive.client.find_vault_file(PROFILE) is None


def test_metadata_reports_the_md5_and_version(drive: Any) -> None:
    uploaded = _upload(drive)
    read = drive.client.metadata(uploaded.id)
    assert read.md5 == md5_hex(VAULT)
    assert read.version == uploaded.version
    assert read.trashed is False


def test_metadata_for_an_unknown_file_raises(drive: Any) -> None:
    with pytest.raises(RemoteMissing):
        drive.client.metadata("no-such-file")


def test_upload_sends_the_exact_bytes_and_returns_the_new_md5(drive: Any) -> None:
    uploaded = _upload(drive)
    assert uploaded.md5 == md5_hex(VAULT)
    assert uploaded.version is not None and uploaded.version >= 1
    assert uploaded.head_revision_id
    assert drive.stored_bytes(uploaded.id) == VAULT


def test_uploading_again_keeps_one_file_and_bumps_the_version(drive: Any) -> None:
    first = _upload(drive)
    second = _upload(drive, OTHERS, file_id=first.id)
    assert second.id == first.id
    assert second.version is not None and first.version is not None
    assert second.version > first.version
    assert drive.stored_bytes(first.id) == OTHERS
    assert drive.client.find_vault_file(PROFILE).id == first.id  # type: ignore[union-attr]


def test_download_returns_the_bytes(drive: Any) -> None:
    uploaded = _upload(drive, OTHERS)
    assert drive.client.download(uploaded.id, expect_md5=uploaded.md5) == OTHERS


def test_a_download_that_does_not_match_the_md5_is_refused(drive: Any) -> None:
    uploaded = _upload(drive)
    with pytest.raises(RemoteUnreadable):
        drive.client.download(uploaded.id, expect_md5=md5_hex(OTHERS))


def test_revisions_are_newest_first_and_keep_the_old_bytes(drive: Any) -> None:
    first = _upload(drive)
    second = _upload(drive, OTHERS, file_id=first.id)
    revisions = drive.client.list_revisions(first.id)
    assert [r.id for r in revisions][0] == second.head_revision_id
    assert revisions[-1].id == first.head_revision_id
    assert drive.client.download_revision(first.id, first.head_revision_id or "") == VAULT


def test_the_folder_is_created_once(drive: Any) -> None:
    root = drive.client.ensure_folder("PersonalVault")
    again = drive.client.ensure_folder("PersonalVault")
    inside = drive.client.ensure_folder(PROFILE, root)
    assert again == root
    assert inside != root


def test_both_implementations_satisfy_the_interface() -> None:
    assert isinstance(HttpDriveClient(token=lambda: TOKEN, session=StubSession()), DriveClient)
    assert isinstance(FakeDrive(), DriveClient)


# --- the real client only --------------------------------------------------


def test_every_request_carries_the_bearer_token_and_a_timeout() -> None:
    real = RealDrive()
    uploaded = _upload(real)
    real.client.download(uploaded.id)
    assert real.session.calls, "no request was made at all"
    for call in real.session.calls:
        assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert call["timeout"] is not None
        assert "googleapis.com" in call["url"]


def test_upload_sets_the_app_properties() -> None:
    real = RealDrive()
    _upload(real)
    sent = [c for c in real.session.calls if c["url"].startswith(DRIVE_UPLOAD_URL)]
    assert len(sent) == 1
    metadata = json.loads(sent[0]["files"]["metadata"][1])
    assert metadata["appProperties"] == {"pm_profile_id": PROFILE, "pm_schema": "1"}
    assert sent[0]["files"]["file"][1] == VAULT


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AuthExpired),
        (403, AccessDenied),
        (404, RemoteMissing),
        (429, RateLimited),
        (500, ServerError),
        (503, ServerError),
    ],
)
def test_http_statuses_map_to_their_own_errors(status: int, expected: type[Exception]) -> None:
    real = RealDrive()
    real.session.status = status
    with pytest.raises(expected):
        real.client.find_vault_file(PROFILE)


@pytest.mark.parametrize(
    "boom", [requests.Timeout("too slow"), requests.ConnectionError("no route")]
)
def test_a_dead_network_is_retryable(boom: Exception) -> None:
    real = RealDrive()
    real.session.raise_ = boom
    with pytest.raises(NetworkError):
        real.client.metadata("file-1")


def test_every_failure_has_its_own_code() -> None:
    """The UI maps codes to sentences, so no two failures share one."""
    from personal_vault.sync.errors import RetryableSyncError, SyncError

    failures = [
        AuthExpired("401"),
        AccessDenied("403"),
        RemoteMissing("404"),
        RateLimited("429"),
        ServerError("500"),
        NetworkError("timeout"),
        RemoteUnreadable("bytes"),
    ]
    assert all(isinstance(failure, SyncError) for failure in failures)
    assert all(isinstance(failure, RetryableSyncError) for failure in failures[3:6])
    codes = [failure.code for failure in failures]
    assert len(set(codes)) == len(codes)


# --- the fake's failure injection ------------------------------------------


def test_the_fake_can_go_offline() -> None:
    fake = FakeDrive()
    fake.offline = True
    with pytest.raises(NetworkError):
        fake.find_vault_file(PROFILE)


def test_the_fake_can_return_a_429_or_a_5xx() -> None:
    fake = FakeDrive()
    fake.failures = [RateLimited("429"), ServerError("500"), NetworkError("offline")]
    for expected in (RateLimited, ServerError, NetworkError):
        with pytest.raises(expected):
            fake.ensure_folder("PersonalVault")
    assert fake.ensure_folder("PersonalVault")  # the queue has run out


def test_the_fake_can_corrupt_a_download() -> None:
    fake = FakeDrive()
    file_id = fake.write_from_another_device(VAULT, profile_id=PROFILE)
    fake.corrupt_downloads = True
    with pytest.raises(RemoteUnreadable):
        fake.download(file_id, expect_md5=md5_hex(VAULT))


def test_another_device_can_write_during_our_upload() -> None:
    """The race in sync.md: it lands after our check and before our write."""
    fake = FakeDrive()
    first = fake.upload(
        file_id=None, name="vault.kdbx", parent_id="folder-1", data=VAULT, profile_id=PROFILE
    )
    fake.before["upload"] = lambda drive: drive.write_from_another_device(
        OTHERS, profile_id=PROFILE
    )

    ours = fake.upload(
        file_id=first.id, name="vault.kdbx", parent_id="folder-1", data=VAULT, profile_id=PROFILE
    )

    revisions = [r.id for r in fake.list_revisions(first.id)]
    assert revisions[0] == ours.head_revision_id  # our write is the newest
    assert revisions[1] != first.head_revision_id  # theirs, silently overwritten…
    assert fake.download_revision(first.id, revisions[1]) == OTHERS  # …and still recoverable
    assert revisions[2] == first.head_revision_id
    assert fake.calls == ["upload", "upload", "list_revisions", "download_revision"]


def test_no_call_logs_a_token_or_a_body(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    real = RealDrive()
    with caplog.at_level(logging.DEBUG):
        uploaded = _upload(real)
        real.client.find_vault_file(PROFILE)
        real.client.metadata(uploaded.id)
        real.client.download(uploaded.id)
        real.client.list_revisions(uploaded.id)
    captured = capsys.readouterr()
    for where in (caplog.text, captured.out, captured.err):
        assert TOKEN not in where
        assert "kdbx-bytes" not in where
