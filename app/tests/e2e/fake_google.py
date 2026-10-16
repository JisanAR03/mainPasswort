"""A fake Google for the extension-only e2e tests: the Drive v3 calls the
extension makes, and the OAuth redirect chrome.identity.launchWebAuthFlow follows.

It keeps files and revisions in memory (revisions listed oldest first, with a
modifiedTime, as Drive documents them), checks the bearer token on every call,
and has switches for what the tests must see the extension survive: the
network gone, a revoked sign-in, a full Drive, a write from another device, a
file in the bin. The test copy of the extension points config.js at it.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

FOLDER_MIME = "application/vnd.google-apps.folder"
_BASE_TIME = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


@dataclass
class Revision:
    id: str
    content: bytes
    modified: str


@dataclass
class DriveFile:
    id: str
    name: str
    mime: str
    parents: list[str]
    app_properties: dict[str, str] = field(default_factory=dict)
    revisions: list[Revision] = field(default_factory=list)  # oldest first
    trashed: bool = False

    @property
    def content(self) -> bytes:
        return self.revisions[-1].content if self.revisions else b""

    def resource(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "mimeType": self.mime,
            "parents": self.parents,
            "trashed": self.trashed,
            "appProperties": self.app_properties,
        }
        if self.mime != FOLDER_MIME:
            item.update(
                md5Checksum=hashlib.md5(self.content).hexdigest(),  # noqa: S324 - Drive's checksum
                version=str(len(self.revisions)),
                size=str(len(self.content)),
                headRevisionId=self.revisions[-1].id,
                modifiedTime=self.revisions[-1].modified,
            )
        return item


class FakeGoogle:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.files: dict[str, DriveFile] = {}
        self.tokens: set[str] = set()
        self.email = "owner@example.com"
        self.offline = False  # drop every connection without an answer
        self.revoked = False  # the sign-in no longer works: auth fails, tokens refused
        self.quota_full = False  # uploads refused with storageQuotaExceeded
        self.calls: list[str] = []
        self._ids = itertools.count(1)
        self._clock = itertools.count(1)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()

    def reset(self) -> None:
        with self.lock:
            self.files.clear()
            self.tokens.clear()
            self.offline = self.revoked = self.quota_full = False
            self.calls.clear()

    # --- what tests do from the outside -----------------------------------------

    def _stamp(self) -> str:
        moment = _BASE_TIME + timedelta(seconds=next(self._clock))
        return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    def add_revision(self, file: DriveFile, content: bytes) -> None:
        file.revisions.append(Revision(self._new_id("rev"), content, self._stamp()))

    def put_vault(self, profile_id: str, content: bytes) -> DriveFile:
        """A vault another device (the desktop app) already uploaded."""
        with self.lock:
            folder = self._folder("PersonalVault")
            file = DriveFile(
                self._new_id("file"),
                "vault.kdbx",
                "application/octet-stream",
                [folder.id],
                {"pm_profile_id": profile_id, "pm_schema": "1"},
            )
            self.add_revision(file, content)
            self.files[file.id] = file
            return file

    def write_from_other_device(self, profile_id: str, content: bytes) -> None:
        with self.lock:
            self.add_revision(self.vault_of(profile_id), content)

    def vault_of(self, profile_id: str) -> DriveFile:
        found = [
            f for f in self.files.values() if f.app_properties.get("pm_profile_id") == profile_id
        ]
        assert found, f"no vault on the fake Drive for {profile_id}"
        return found[0]

    def has_vault(self, profile_id: str) -> bool:
        with self.lock:
            return any(
                f.app_properties.get("pm_profile_id") == profile_id for f in self.files.values()
            )

    def _folder(self, name: str) -> DriveFile:
        for f in self.files.values():
            if f.mime == FOLDER_MIME and f.name == name and not f.trashed:
                return f
        folder = DriveFile(self._new_id("folder"), name, FOLDER_MIME, ["root"])
        self.files[folder.id] = folder
        return folder

    # --- the HTTP side -------------------------------------------------------------

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        google = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

            def _reply(self, status: int, body: Any = None, raw: bytes | None = None) -> None:
                data = (
                    raw
                    if raw is not None
                    else json.dumps(body if body is not None else {}).encode()
                )
                self.send_response(status)
                self.send_header(
                    "Content-Type",
                    "application/octet-stream" if raw is not None else "application/json",
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _error(self, status: int, reason: str = "error") -> None:
                self._reply(status, {"error": {"code": status, "errors": [{"reason": reason}]}})

            def _authorized(self) -> bool:
                header = self.headers.get("Authorization", "")
                token = header.removeprefix("Bearer ")
                return not google.revoked and token in google.tokens

            def _route(self, method: str) -> None:
                if google.offline:
                    self.close_connection = True  # no answer at all: a network failure
                    return
                parts = urlsplit(self.path)
                query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
                google.calls.append(f"{method} {parts.path}")
                if parts.path == "/auth":
                    return self._auth(query)
                if not self._authorized():
                    return self._error(401, "authError")
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                with google.lock:
                    self._drive(method, parts.path, query, body)

            def do_GET(self) -> None:  # noqa: N802
                self._route("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._route("POST")

            def do_PATCH(self) -> None:  # noqa: N802
                self._route("PATCH")

            def _auth(self, query: dict[str, str]) -> None:
                redirect = query.get("redirect_uri", "")
                state = query.get("state", "")
                if google.revoked:
                    fragment = urlencode({"error": "interaction_required", "state": state})
                else:
                    token = f"fake-token-{next(google._ids)}"
                    google.tokens.add(token)
                    fragment = urlencode(
                        {
                            "access_token": token,
                            "token_type": "Bearer",
                            "expires_in": "3599",
                            "scope": query.get("scope", ""),
                            "state": state,
                        }
                    )
                self.send_response(302)
                self.send_header("Location", f"{redirect}#{fragment}")
                self.end_headers()

            def _drive(self, method: str, path: str, query: dict[str, str], body: bytes) -> None:
                if path == "/drive/v3/about":
                    return self._reply(200, {"user": {"emailAddress": google.email}})
                if path == "/drive/v3/files" and method == "GET":
                    return self._reply(
                        200, {"files": [f.resource() for f in self._search(query.get("q", ""))]}
                    )
                if path == "/drive/v3/files" and method == "POST":
                    meta = json.loads(body or b"{}")
                    folder = DriveFile(
                        google._new_id("folder"),
                        meta.get("name", ""),
                        meta.get("mimeType", ""),
                        meta.get("parents", ["root"]),
                    )
                    google.files[folder.id] = folder
                    return self._reply(200, {"id": folder.id})
                match = re.fullmatch(r"/drive/v3/files/([^/]+)(?:/revisions(?:/([^/]+))?)?", path)
                if match and method == "GET":
                    return self._file_get(match.group(1), path, match.group(2), query)
                match = re.fullmatch(r"/upload/drive/v3/files(?:/([^/]+))?", path)
                if match and method in ("POST", "PATCH"):
                    return self._upload(match.group(1), body)
                return self._error(404, "notFound")

            def _file_get(
                self, file_id: str, path: str, revision_id: str | None, query: dict[str, str]
            ) -> None:
                file = google.files.get(file_id)
                if file is None:
                    return self._error(404, "notFound")
                if path.endswith("/revisions"):
                    revisions = [{"id": r.id, "modifiedTime": r.modified} for r in file.revisions]
                    return self._reply(200, {"revisions": revisions})
                if revision_id is not None:
                    revision = next((r for r in file.revisions if r.id == revision_id), None)
                    if revision is None:
                        return self._error(404, "notFound")
                    return self._reply(200, raw=revision.content)
                if query.get("alt") == "media":
                    return self._reply(200, raw=file.content)
                return self._reply(200, file.resource())

            def _search(self, q: str) -> list[DriveFile]:
                found = list(google.files.values())
                trashed = re.search(r"trashed = (true|false)", q)
                if trashed:
                    found = [f for f in found if f.trashed == (trashed.group(1) == "true")]
                for key, value in re.findall(
                    r"appProperties has \{ key='([^']*)' and value='([^']*)' \}", q
                ):
                    found = [f for f in found if f.app_properties.get(key) == value]
                name = re.search(r"name = '([^']*)'", q)
                if name:
                    found = [f for f in found if f.name == name.group(1)]
                mime = re.search(r"mimeType = '([^']*)'", q)
                if mime:
                    found = [f for f in found if f.mime == mime.group(1)]
                return found

            def _upload(self, file_id: str | None, body: bytes) -> None:
                if google.quota_full:
                    return self._error(403, "storageQuotaExceeded")
                boundary = re.search(r"boundary=([^;]+)", self.headers.get("Content-Type", ""))
                if not boundary:
                    return self._error(400, "badRequest")
                marker = b"--" + boundary.group(1).encode()
                parts = [p for p in body.split(marker) if p not in (b"", b"--", b"--\r\n")]
                meta_part, data_part = parts[0], parts[1]
                meta = json.loads(meta_part.split(b"\r\n\r\n", 1)[1].strip())
                content = data_part.split(b"\r\n\r\n", 1)[1]
                content = content[:-2] if content.endswith(b"\r\n") else content
                if file_id is None:
                    file = DriveFile(
                        google._new_id("file"),
                        meta.get("name", ""),
                        "application/octet-stream",
                        meta.get("parents", ["root"]),
                        dict(meta.get("appProperties", {})),
                    )
                    google.files[file.id] = file
                else:
                    file = google.files.get(file_id)
                    if file is None:
                        return self._error(404, "notFound")
                    file.app_properties.update(meta.get("appProperties", {}))
                google.add_revision(file, content)
                return self._reply(200, file.resource())

        return Handler
