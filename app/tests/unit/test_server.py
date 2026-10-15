"""M3-02: the local socket server — framing, dispatch, rate limit (pytest-qt).

An in-process QLocalSocket client speaks to a real QLocalServer, so the
framing, dispatch and per-key token bucket are exercised end to end over a
genuine socket, not mocked calls.
"""

from __future__ import annotations

import json
import struct
import uuid

import pytest
from fixtures.weak_vault import make_login
from personal_vault.bridge.backend import VaultBackend
from personal_vault.bridge.protocol import MAX_REQUEST_BYTES, frame
from personal_vault.bridge.server import BridgeServer, TokenBucket
from personal_vault.core.models import SecretStr
from personal_vault.core.vault import VaultSession
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.unit

KEY = "pairing-key-1"
OTHER_KEY = "pairing-key-2"


class Pairing:
    """Accepts two known keys; records pair requests."""

    def key_valid(self, key: str) -> bool:
        return key in (KEY, OTHER_KEY)

    def accept(self, key: str, browser_name: str) -> bool:
        return False


def _request(kind: str, payload: dict[str, object], key: str = KEY, req_id: str = "req-1") -> bytes:
    return json.dumps(
        {"v": 1, "id": req_id, "type": kind, "pairing_key": key, "payload": payload}
    ).encode()


def _connected() -> QLocalSocket.LocalSocketState:
    return QLocalSocket.LocalSocketState.ConnectedState


def _connect(qtbot: QtBot, name: str) -> QLocalSocket:
    sock = QLocalSocket()
    sock.connectToServer(name)
    qtbot.waitUntil(lambda: sock.state() == _connected(), timeout=5000)
    return sock


def _recv(qtbot: QtBot, sock: QLocalSocket) -> bytes:
    qtbot.waitUntil(lambda: sock.bytesAvailable() >= 4, timeout=5000)
    (length,) = struct.unpack("=I", bytes(sock.read(4)))
    qtbot.waitUntil(lambda: sock.bytesAvailable() >= length, timeout=5000)
    return bytes(sock.read(length))


def _exchange(qtbot: QtBot, name: str, raw: bytes) -> tuple[QLocalSocket, bytes]:
    sock = _connect(qtbot, name)
    frame_raw = frame(raw)
    assert sock.write(frame_raw) == len(frame_raw)
    sock.flush()
    return sock, _recv(qtbot, sock)


@pytest.fixture
def server(qtbot: QtBot, weak_session: VaultSession) -> BridgeServer:
    backend = VaultBackend(weak_session, "Test Profile", show_unlock=lambda: None)
    bridge = BridgeServer(backend, Pairing())
    name = f"pv-test-{uuid.uuid4().hex}"
    assert bridge.listen(name)
    yield bridge
    bridge.close()


def test_round_trip_over_a_real_socket(
    qtbot: QtBot, server: BridgeServer, weak_session: VaultSession
) -> None:
    weak_session.add(make_login(title="Match", urls=["https://example.com"]))
    weak_session.save()
    sock, raw = _exchange(
        qtbot, server.server.serverName(), _request("get_logins", {"url": "https://example.com"})
    )
    reply = json.loads(raw)
    assert reply == {
        "v": 1,
        "id": "req-1",
        "ok": True,
        "result": {
            "logins": [
                {
                    "id": str(weak_session.list_logins()[0].id),
                    "title": "Match",
                    "username": "user@example.com",
                }
            ]
        },
    }
    sock.disconnectFromServer()


def test_back_to_back_requests_each_get_their_own_reply(qtbot: QtBot, server: BridgeServer) -> None:
    sock = _connect(qtbot, server.server.serverName())
    sock.write(frame(_request("hello", {"extension_version": "1.0"})))
    sock.write(frame(_request("lock", {}, req_id="req-2")))
    sock.flush()
    first, second = json.loads(_recv(qtbot, sock)), json.loads(_recv(qtbot, sock))
    assert first["id"] == "req-1" and first["ok"] is True
    assert second["id"] == "req-2" and second["result"] == {}
    sock.disconnectFromServer()


def test_oversized_declared_length_gets_too_large_and_closes(
    qtbot: QtBot, server: BridgeServer
) -> None:
    sock = _connect(qtbot, server.server.serverName())
    sock.write(struct.pack("=I", MAX_REQUEST_BYTES + 1))  # length only, no body
    sock.flush()
    reply = json.loads(_recv(qtbot, sock))
    assert reply["ok"] is False
    assert reply["error"] == {"code": "too_large"}
    qtbot.waitUntil(
        lambda: sock.state() == QLocalSocket.LocalSocketState.UnconnectedState, timeout=5000
    )


def test_socket_is_restricted_to_the_current_user(server: BridgeServer) -> None:
    assert server.server.socketOptions() & QLocalServer.SocketOption.UserAccessOption


def test_get_secret_is_rate_limited_per_key(
    qtbot: QtBot, server: BridgeServer, weak_session: VaultSession
) -> None:
    entry = make_login(password=SecretStr("the-password"), urls=["https://example.com"])
    weak_session.add(entry)
    weak_session.save()
    sock = _connect(qtbot, server.server.serverName())
    payload = {"entry_id": str(entry.id), "url": "https://example.com/login"}

    for i in range(10):
        sock.write(frame(_request("get_secret", payload, req_id=f"r-{i}")))
        sock.flush()
        reply = json.loads(_recv(qtbot, sock))
        assert reply["ok"] is True, (i, reply)

    sock.write(frame(_request("get_secret", payload, req_id="r-11")))
    sock.flush()
    eleventh = json.loads(_recv(qtbot, sock))
    assert eleventh["ok"] is False
    assert eleventh["error"] == {"code": "rate_limited"}

    # the other pairing key has its own allowance
    sock.write(frame(_request("get_secret", payload, key=OTHER_KEY, req_id="r-other")))
    sock.flush()
    other = json.loads(_recv(qtbot, sock))
    assert other["ok"] is True
    sock.disconnectFromServer()


def test_bad_json_gets_bad_request_and_connection_stays_usable(
    qtbot: QtBot, server: BridgeServer
) -> None:
    sock = _connect(qtbot, server.server.serverName())
    sock.write(frame(b"this is not json"))
    sock.flush()
    reply = json.loads(_recv(qtbot, sock))
    assert reply["error"] == {"code": "bad_request"}
    sock.write(frame(_request("hello", {"extension_version": "1.0"})))
    sock.flush()
    hello = json.loads(_recv(qtbot, sock))
    assert hello["ok"] is True
    sock.disconnectFromServer()


# --- the token bucket itself, with an injected clock ---


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_token_bucket_refills_ten_per_minute_per_key() -> None:
    clock = Clock()
    bucket = TokenBucket(capacity=10, tokens_per_second=10 / 60, now=clock)
    for _ in range(10):
        assert bucket.take("a") is True
    assert bucket.take("a") is False
    assert bucket.take("b") is True  # a second key is unaffected
    clock.advance(6.0)
    assert bucket.take("a") is True
    assert bucket.take("a") is False
    clock.advance(3600.0)
    for _ in range(10):
        assert bucket.take("a") is True
    assert bucket.take("a") is False  # refill caps at the capacity
