"""M3-01: bridge protocol parsing, size limits and dispatch (pure, no sockets)."""

from __future__ import annotations

import json
import uuid

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from personal_vault.bridge.protocol import (
    ERROR_CODES,
    MAX_REQUEST_BYTES,
    REQUEST_TYPES,
    Dispatcher,
    parse_request,
)
from personal_vault.core.models import LoginSummary, SecretStr

pytestmark = pytest.mark.unit

ALL_TYPES = frozenset(
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

GOOD_KEY = "pairing-key-abc"


def envelope(kind: str, payload: object | None = None, key: str | None = GOOD_KEY) -> bytes:
    message: dict[str, object] = {"v": 1, "id": "req-1", "type": kind}
    if key is not None:
        message["pairing_key"] = key
    message["payload"] = {} if payload is None else payload
    return json.dumps(message).encode()


PAYLOADS: dict[str, object] = {
    "hello": {"extension_version": "1.2.3"},
    "pair_request": {"key": GOOD_KEY, "browser_name": "Chrome"},
    "show_unlock": {},
    "get_logins": {"url": "https://example.com/login"},
    "get_secret": {"entry_id": "e-1", "url": "https://example.com/login"},
    "save_login": {
        "url": "https://example.com/login",
        "username": "user@example.com",
        "password": "pw",
        "title": "Example",
    },
    "update_password": {
        "entry_id": "e-1",
        "url": "https://example.com/login",
        "new_password": "pw",
    },
    "generate_password": {"length": 24},
    "lock": {},
}


class FakeBackend:
    """A scripted backend: every method records its call and returns fixed data."""

    def __init__(self) -> None:
        self.unlocked_state = True
        self.version = "9.9.9"
        self.profile_name = "Test Profile"
        self.logins: list[LoginSummary] = []
        self.secret: tuple[str, SecretStr] | None = (
            "user@example.com",
            SecretStr("the-password"),
        )
        self.locked_calls = 0
        self.shown_calls = 0
        self.saved: list[tuple[str, str, SecretStr, str | None]] = []
        self.updated: list[tuple[str, str, SecretStr]] = []
        self.generated: list[int | None] = []

    def unlocked(self) -> bool:
        return self.unlocked_state

    def app_info(self) -> tuple[str, str]:
        return self.version, self.profile_name

    def matching_logins(self, url: str) -> list[LoginSummary]:
        return self.logins

    def secret_for(self, entry_id: str, url: str) -> tuple[str, SecretStr] | None:
        return self.secret

    def save_login(self, url: str, username: str, password: SecretStr, title: str | None) -> str:
        self.saved.append((url, username, password, title))
        return "new-entry-id"

    def update_password(self, entry_id: str, url: str, new_password: SecretStr) -> None:
        self.updated.append((entry_id, url, new_password))

    def generate(self, length: int | None) -> str:
        self.generated.append(length)
        return "generated-password"

    def lock(self) -> None:
        self.locked_calls += 1

    def show_unlock(self) -> None:
        self.shown_calls += 1


class FakePairing:
    def __init__(self, valid_keys: set[str] | None = None) -> None:
        self._valid = valid_keys or {GOOD_KEY}
        self.accepted: list[tuple[str, str]] = []

    def key_valid(self, key: str) -> bool:
        return key in self._valid

    def accept(self, key: str, browser_name: str) -> bool:
        self.accepted.append((key, browser_name))
        self._valid.add(key)
        return True


def make_dispatcher(
    backend: FakeBackend | None = None,
    pairing: FakePairing | None = None,
    secret_allowed: bool = True,
) -> Dispatcher:
    return Dispatcher(
        backend or FakeBackend(),
        pairing or FakePairing(),
        secret_allowed=lambda key: secret_allowed,
    )


def reply_of(raw: bytes) -> dict[str, object]:
    reply = json.loads(raw)
    assert isinstance(reply, dict)
    return reply


def test_parse_accepts_every_message_type() -> None:
    for kind in ALL_TYPES:
        request = parse_request(envelope(kind, PAYLOADS[kind]))
        assert request.type == kind
        assert request.id == "req-1"
        assert request.pairing_key == GOOD_KEY


def test_unknown_type_gets_an_error_reply() -> None:
    raw = make_dispatcher().dispatch(envelope("list_all_entries", {}))
    reply = reply_of(raw)
    assert reply["ok"] is False
    assert reply["error"] == {"code": "bad_request"}


def test_unknown_fields_and_wrong_types_are_rejected() -> None:
    dispatcher = make_dispatcher()
    bad_envelopes = [
        json.dumps(
            {
                "v": 1,
                "id": "r",
                "type": "get_logins",
                "pairing_key": GOOD_KEY,
                "payload": {"url": "https://e.com"},
                "extra": 1,
            }
        ).encode(),
        json.dumps(
            {
                "v": 1,
                "id": "r",
                "type": "get_logins",
                "pairing_key": GOOD_KEY,
                "payload": {"url": "https://e.com", "query": "x"},
            }
        ).encode(),
        envelope("get_logins", {"url": 5}),
        envelope("get_logins", {}),  # missing url
        envelope("generate_password", {"length": True}),  # bool is not an int
        envelope("get_logins", PAYLOADS["get_logins"], key=7),  # pairing_key not a str
        json.dumps({"v": "1", "id": "r", "type": "get_logins", "payload": {}}).encode(),
        json.dumps({"v": 2, "id": "r", "type": "get_logins", "payload": {}}).encode(),
        json.dumps({"v": 1, "id": "", "type": "get_logins", "payload": {}}).encode(),
        json.dumps({"v": 1, "id": "r", "payload": {}}).encode(),  # no type
        b"not json at all",
    ]
    for raw in bad_envelopes:
        reply = reply_of(dispatcher.dispatch(raw))
        assert reply["ok"] is False, raw
        assert reply["error"] == {"code": "bad_request"}, raw


def test_oversized_requests_get_too_large() -> None:
    raw = make_dispatcher().dispatch(b"x" * (MAX_REQUEST_BYTES + 1))
    reply = reply_of(raw)
    assert reply["error"] == {"code": "too_large"}


def test_dispatch_exposes_exactly_the_nine_types() -> None:
    assert set(REQUEST_TYPES) == ALL_TYPES


@given(st.binary(max_size=64 * 1024))
@hyp_settings(max_examples=200)
def test_fuzz_never_crashes_and_always_answers(raw: bytes) -> None:
    dispatcher = make_dispatcher()
    reply = reply_of(dispatcher.dispatch(raw))
    assert reply["v"] == 1
    if reply["ok"] is True:
        assert "result" in reply and "error" not in reply
    else:
        assert isinstance(reply["error"], dict)
        assert reply["error"]["code"] in ERROR_CODES


def test_locked_vault_answers_vault_requests_with_locked() -> None:
    backend = FakeBackend()
    backend.unlocked_state = False
    dispatcher = make_dispatcher(backend)
    for kind in ("get_logins", "get_secret", "save_login", "update_password"):
        reply = reply_of(dispatcher.dispatch(envelope(kind, PAYLOADS[kind])))
        assert reply == {
            "v": 1,
            "id": "req-1",
            "ok": False,
            "error": {"code": "locked"},
        }, kind
    hello = reply_of(dispatcher.dispatch(envelope("hello", PAYLOADS["hello"])))
    assert hello["ok"] is True
    assert hello["result"]["state"] == "locked"
    generated = reply_of(
        dispatcher.dispatch(envelope("generate_password", PAYLOADS["generate_password"]))
    )
    assert generated["ok"] is True


def test_unpaired_requests_are_refused() -> None:
    dispatcher = make_dispatcher()
    for kind in ("get_logins", "get_secret", "save_login", "update_password", "lock"):
        reply = reply_of(dispatcher.dispatch(envelope(kind, PAYLOADS[kind], key="wrong")))
        assert reply["error"] == {"code": "not_paired"}, kind
    # the unpaired-ok set still works without a valid key
    for kind in ("hello", "show_unlock", "generate_password", "pair_request"):
        reply = reply_of(dispatcher.dispatch(envelope(kind, PAYLOADS[kind], key="wrong")))
        assert reply["ok"] is True, kind


def test_get_secret_rematches_the_url() -> None:
    backend = FakeBackend()
    backend.secret = None  # the backend found no entry whose URLs match the tab
    dispatcher = make_dispatcher(backend)
    reply = reply_of(dispatcher.dispatch(envelope("get_secret", PAYLOADS["get_secret"])))
    assert reply["error"] == {"code": "url_mismatch"}


def test_get_secret_rate_limit() -> None:
    dispatcher = make_dispatcher(secret_allowed=False)
    reply = reply_of(dispatcher.dispatch(envelope("get_secret", PAYLOADS["get_secret"])))
    assert reply["error"] == {"code": "rate_limited"}


def test_pair_request_accept_returns_paired_true() -> None:
    pairing = FakePairing(valid_keys=set())
    dispatcher = make_dispatcher(pairing=pairing)
    reply = reply_of(dispatcher.dispatch(envelope("pair_request", PAYLOADS["pair_request"])))
    assert reply["ok"] is True
    assert reply["result"] == {"paired": True}
    assert pairing.accepted == [(GOOD_KEY, "Chrome")]


def test_success_reply_shapes() -> None:
    backend = FakeBackend()
    dispatcher = make_dispatcher(backend)

    hello = reply_of(dispatcher.dispatch(envelope("hello", PAYLOADS["hello"])))
    assert hello["result"] == {
        "app_version": "9.9.9",
        "state": "unlocked",
        "profile_name": "Test Profile",
    }

    summaries = [
        LoginSummary(id=uuid.uuid4(), title=f"Entry {i}", username=f"u{i}", hosts=("example.com",))
        for i in range(25)
    ]
    backend.logins = summaries
    logins = reply_of(dispatcher.dispatch(envelope("get_logins", PAYLOADS["get_logins"])))
    assert len(logins["result"]["logins"]) == 20  # capped, never the full list

    saved = reply_of(dispatcher.dispatch(envelope("save_login", PAYLOADS["save_login"])))
    assert saved["result"] == {"entry_id": "new-entry-id"}
    assert len(backend.saved) == 1

    updated = reply_of(
        dispatcher.dispatch(envelope("update_password", PAYLOADS["update_password"]))
    )
    assert updated["result"] == {"entry_id": "e-1"}

    generated = reply_of(
        dispatcher.dispatch(envelope("generate_password", PAYLOADS["generate_password"]))
    )
    assert generated["result"] == {"password": "generated-password"}
    assert backend.generated == [24]

    locked = reply_of(dispatcher.dispatch(envelope("lock", PAYLOADS["lock"])))
    assert locked["result"] == {}
    assert backend.locked_calls == 1

    shown = reply_of(dispatcher.dispatch(envelope("show_unlock", PAYLOADS["show_unlock"])))
    assert shown["result"] == {"shown": True}
    assert backend.shown_calls == 1


def test_replies_stay_under_the_64kb_cap() -> None:
    backend = FakeBackend()
    backend.logins = [
        LoginSummary(id=uuid.uuid4(), title="t" * 2000, username="u" * 2000, hosts=("example.com",))
        for _ in range(20)
    ]
    dispatcher = make_dispatcher(backend)
    raw = dispatcher.dispatch(envelope("get_logins", PAYLOADS["get_logins"]))
    assert len(raw) < 64 * 1024


def test_internal_errors_never_leak_details() -> None:
    backend = FakeBackend()

    def boom(url: str) -> list[LoginSummary]:
        raise RuntimeError(f"secret detail {SecretStr('x')}")

    backend.matching_logins = boom  # type: ignore[method-assign]
    dispatcher = make_dispatcher(backend)
    reply = reply_of(dispatcher.dispatch(envelope("get_logins", PAYLOADS["get_logins"])))
    assert reply["error"] == {"code": "internal"}
