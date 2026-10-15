"""Bridge message protocol ([S]): strict parsing, size limits and dispatch.

Pure Python, no Qt and no sockets, so every rule is unit-testable. Requests
are parsed against strict per-type schemas: unknown fields and wrong types are
rejected, never ignored. Dispatch allows exactly the nine message types of
docs/specs/browser-protocol.md and nothing else.

Invariants:
- I4: ``get_secret``/``update_password`` re-match the URL; a mismatch gets
  ``url_mismatch`` and never the password.
- I5: a locked vault answers every vault request with ``locked`` and nothing
  else.
"""

from __future__ import annotations

import json
import logging
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from personal_vault.core.models import LoginSummary, SecretStr

logger = logging.getLogger("pv.bridge")

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 16 * 1024
MAX_REPLY_BYTES = 64 * 1024
MAX_LOGINS_PER_REPLY = 20
# The rendezvous name the app's server and the native host agree on (Qt-free so
# the host process can import it without Qt).
SOCKET_NAME = "personal-vault-bridge"

ERROR_CODES = frozenset(
    {
        "locked",
        "not_paired",
        "no_match",
        "url_mismatch",
        "bad_request",
        "too_large",
        "rate_limited",
        "app_not_running",
        "internal",
    }
)

# Types that need the vault, so a locked vault refuses them (I5).
VAULT_TYPES = frozenset({"get_logins", "get_secret", "save_login", "update_password"})
# Types allowed without a pairing key (browser-protocol.md "Needs pairing" column).
UNPAIRED_OK = frozenset({"hello", "pair_request", "show_unlock", "generate_password"})

REQUEST_TYPES = frozenset(
    {
        "hello",
        "pair_request",
        "show_unlock",
        "get_logins",
        "get_secret",
        "save_login",
        "update_password",
        "generate_password",
        "lock",
    }
)

# Per-type payload schema: field name -> allowed JSON type(s). A field that may
# also be absent or null is listed in _OPTIONAL_FIELDS.
_PAYLOAD_FIELDS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "hello": {"extension_version": str},
    "pair_request": {"key": str, "browser_name": str},
    "show_unlock": {},
    "get_logins": {"url": str},
    "get_secret": {"entry_id": str, "url": str},
    "save_login": {"url": str, "username": str, "password": str, "title": str},
    "update_password": {"entry_id": str, "url": str, "new_password": str},
    "generate_password": {"length": int},
    "lock": {},
}
_OPTIONAL_FIELDS: dict[str, frozenset[str]] = {
    "save_login": frozenset({"title"}),
    "generate_password": frozenset({"length"}),
}


class ProtocolError(Exception):
    """A request failed a protocol rule; ``code`` is one of ERROR_CODES."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class UrlMismatchError(Exception):
    """The backend refused to return a secret for a non-matching URL (I4)."""


class BridgeBackend(Protocol):
    """The operations dispatch may call; the only door from the bridge to the vault."""

    def unlocked(self) -> bool: ...

    def app_info(self) -> tuple[str, str]:
        """(app version, profile name) — no vault data."""

    def matching_logins(self, url: str) -> list[LoginSummary]: ...

    def secret_for(self, entry_id: str, url: str) -> tuple[str, SecretStr] | None: ...

    def save_login(
        self, url: str, username: str, password: SecretStr, title: str | None
    ) -> str: ...

    def update_password(self, entry_id: str, url: str, new_password: SecretStr) -> None: ...

    def generate(self, length: int | None) -> str: ...

    def lock(self) -> None: ...

    def show_unlock(self) -> None: ...


class Pairing(Protocol):
    """Pairing state: which keys are accepted, and whether a pair request is granted."""

    def key_valid(self, key: str) -> bool: ...

    def accept(self, key: str, browser_name: str) -> bool: ...


@dataclass(frozen=True)
class Request:
    id: str
    type: str
    pairing_key: str | None
    payload: dict[str, Any]


def _fail(code: str) -> None:
    raise ProtocolError(code)


def parse_request(raw: bytes) -> Request:
    """Parse and strictly validate one request; ProtocolError on any violation."""
    if len(raw) > MAX_REQUEST_BYTES:
        _fail("too_large")
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        _fail("bad_request")
    if not isinstance(envelope, dict):
        _fail("bad_request")
    allowed_top = {"v", "id", "type", "pairing_key", "payload"}
    if not set(envelope) <= allowed_top:
        _fail("bad_request")
    if type(envelope.get("v")) is not int or envelope["v"] != PROTOCOL_VERSION:
        _fail("bad_request")
    if not isinstance(envelope.get("id"), str) or not envelope["id"]:
        _fail("bad_request")
    if not isinstance(envelope.get("type"), str) or envelope["type"] not in REQUEST_TYPES:
        _fail("bad_request")
    pairing_key = envelope.get("pairing_key")
    if pairing_key is not None and not isinstance(pairing_key, str):
        _fail("bad_request")
    payload = envelope.get("payload", {})
    if not isinstance(payload, dict):
        _fail("bad_request")
    schema = _PAYLOAD_FIELDS[envelope["type"]]
    if not set(payload) <= set(schema):
        _fail("bad_request")  # unknown payload fields are rejected, never ignored
    for field, allowed in schema.items():
        value = payload.get(field)
        if value is None and field in _OPTIONAL_FIELDS.get(envelope["type"], frozenset()):
            continue
        if type(value) is not allowed:  # exact type: bool is not an int here
            _fail("bad_request")
    return Request(
        id=envelope["id"],
        type=envelope["type"],
        pairing_key=pairing_key,
        payload=payload,
    )


def reply(
    request_id: str,
    *,
    ok: bool,
    result: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> bytes:
    envelope: dict[str, Any] = {"v": PROTOCOL_VERSION, "id": request_id, "ok": ok}
    if ok:
        envelope["result"] = {} if result is None else result
    else:
        envelope["error"] = {"code": error_code}
    raw = json.dumps(envelope).encode()
    if len(raw) > MAX_REPLY_BYTES:
        raise ValueError("reply exceeds the 64 KB cap")
    return raw


def frame(raw: bytes) -> bytes:
    """Native-messaging framing: 4-byte native-order length prefix + payload.

    Shared by the local socket and the stdio host relay (browser-protocol.md
    "Framing"), so both sides of the relay use exactly the same bytes.
    """
    return struct.pack("=I", len(raw)) + raw


class Dispatcher:
    """Routes parsed requests to a backend; ``dispatch`` is total (never raises)."""

    def __init__(
        self,
        backend: BridgeBackend,
        pairing: Pairing,
        secret_allowed: Callable[[str], bool] | None = None,
    ) -> None:
        self._backend = backend
        self._pairing = pairing
        self._secret_allowed = secret_allowed or (lambda key: True)

    def dispatch(self, raw: bytes) -> bytes:
        try:
            return self.handle(parse_request(raw))
        except ProtocolError as exc:
            return reply("", ok=False, error_code=exc.code)
        except Exception as exc:  # never crash the app on hostile input
            logger.error("internal error in bridge dispatch (%s)", type(exc).__name__)
            return reply("", ok=False, error_code="internal")

    def handle(self, request: Request) -> bytes:
        if request.type in VAULT_TYPES and not self._backend.unlocked():
            return reply(request.id, ok=False, error_code="locked")  # I5
        if request.type not in UNPAIRED_OK and not self._pairing.key_valid(
            request.pairing_key or ""
        ):
            return reply(request.id, ok=False, error_code="not_paired")
        try:
            handler = cast(Callable[[Request], bytes], getattr(self, f"_handle_{request.type}"))
            result = handler(request)
        except ProtocolError as exc:
            return reply(request.id, ok=False, error_code=exc.code)
        except UrlMismatchError:
            return reply(request.id, ok=False, error_code="url_mismatch")  # I4
        except Exception as exc:
            logger.error("internal error in %s handler (%s)", request.type, type(exc).__name__)
            return reply(request.id, ok=False, error_code="internal")
        return result

    # --- handlers, one per message type ---

    def _handle_hello(self, request: Request) -> bytes:
        version, profile = self._backend.app_info()
        state = "unlocked" if self._backend.unlocked() else "locked"
        return reply(
            request.id,
            ok=True,
            result={"app_version": version, "state": state, "profile_name": profile},
        )

    def _handle_pair_request(self, request: Request) -> bytes:
        if not self._pairing.accept(request.payload["key"], request.payload["browser_name"]):
            return reply(request.id, ok=False, error_code="not_paired")
        return reply(request.id, ok=True, result={"paired": True})

    def _handle_show_unlock(self, request: Request) -> bytes:
        self._backend.show_unlock()
        return reply(request.id, ok=True, result={"shown": True})

    def _handle_get_logins(self, request: Request) -> bytes:
        logins = self._backend.matching_logins(request.payload["url"])[:MAX_LOGINS_PER_REPLY]
        if not logins:
            return reply(request.id, ok=False, error_code="no_match")
        return reply(
            request.id,
            ok=True,
            result={
                "logins": [
                    {"id": str(login.id), "title": login.title, "username": login.username}
                    for login in logins
                ]
            },
        )

    def _handle_get_secret(self, request: Request) -> bytes:
        key = request.pairing_key or ""
        if not self._secret_allowed(key):
            return reply(request.id, ok=False, error_code="rate_limited")
        secret = self._backend.secret_for(request.payload["entry_id"], request.payload["url"])
        if secret is None:
            return reply(request.id, ok=False, error_code="url_mismatch")
        username, password = secret
        return reply(
            request.id, ok=True, result={"username": username, "password": password.reveal()}
        )

    def _handle_save_login(self, request: Request) -> bytes:
        payload = request.payload
        entry_id = self._backend.save_login(
            url=payload["url"],
            username=payload["username"],
            password=SecretStr(payload["password"]),
            title=payload.get("title"),
        )
        return reply(request.id, ok=True, result={"entry_id": entry_id})

    def _handle_update_password(self, request: Request) -> bytes:
        payload = request.payload
        self._backend.update_password(
            entry_id=payload["entry_id"],
            url=payload["url"],
            new_password=SecretStr(payload["new_password"]),
        )
        return reply(request.id, ok=True, result={"entry_id": payload["entry_id"]})

    def _handle_generate_password(self, request: Request) -> bytes:
        password = SecretStr(self._backend.generate(request.payload.get("length")))
        return reply(request.id, ok=True, result={"password": password.reveal()})

    def _handle_lock(self, request: Request) -> bytes:
        self._backend.lock()
        return reply(request.id, ok=True, result={})
