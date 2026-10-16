"""M3-04: a real subprocess speaks native-messaging framing to the host relay."""

from __future__ import annotations

import gc
import json
import os
import struct
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest
from personal_vault.bridge.protocol import MAX_REQUEST_BYTES, SOCKET_NAME, frame
from personal_vault.bridge.server import BridgeServer
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "app" / "src"
SOCKET_ENV = "PERSONAL_VAULT_SOCKET"

KEY = "pairing-key-host-test"


class Backend:
    def unlocked(self) -> bool:
        return True

    def app_info(self) -> tuple[str, str]:
        return "1.2.3", "Host Test"

    def matching_logins(self, url: str) -> list[object]:
        return []

    def secret_for(self, entry_id: str, url: str) -> object:
        return None

    def save_login(self, url: str, username: str, password: object, title: str | None) -> str:
        return "x"

    def update_password(self, entry_id: str, url: str, new_password: object) -> None:
        return None

    def generate(self, length: int | None) -> str:
        return "generated"

    def lock(self) -> None:
        return None

    def show_unlock(self) -> None:
        return None


class Pairing:
    def key_valid(self, key: str) -> bool:
        return key == KEY

    def accept(self, key: str, browser_name: str) -> bool:
        return False


def _request(kind: str, payload: dict[str, object], key: str = KEY) -> bytes:
    return json.dumps(
        {"v": 1, "id": "host-1", "type": kind, "pairing_key": key, "payload": payload}
    ).encode()


def _read_exact(stream: object, n: int) -> bytes | None:
    chunks = []
    remaining = n
    while remaining:
        chunk = stream.read(remaining)  # type: ignore[attr-defined]
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _start_host(socket_name: str) -> subprocess.Popen[bytes]:
    env = {**os.environ, "PYTHONPATH": str(SRC), SOCKET_ENV: socket_name}
    return subprocess.Popen(
        [sys.executable, "-m", "personal_vault.host.pm_host"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _send_and_recv_pumped(qtbot: QtBot, proc: subprocess.Popen[bytes], framed: bytes) -> bytes:
    """Write one framed payload and read one reply while pumping the Qt loop.

    A plain blocking exchange would deadlock: the host's pipe connect waits for
    the in-process server, the server waits for the event loop, and the event
    loop waits for the exchange. The worker thread does the blocking I/O while
    qtbot.waitUntil pumps the loop.
    """
    result: list[bytes] = []

    def worker() -> None:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(framed)
        proc.stdin.flush()
        header = _read_exact(proc.stdout, 4)
        assert header is not None, "host closed its stdout"
        (length,) = struct.unpack("=I", header)
        body = _read_exact(proc.stdout, length)
        assert body is not None
        result.append(body)

    thread = threading.Thread(target=worker)
    thread.start()
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=15000)
    thread.join()
    return result[0]


def _exchange_pumped(qtbot: QtBot, proc: subprocess.Popen[bytes], raw: bytes) -> bytes:
    return _send_and_recv_pumped(qtbot, proc, frame(raw))


def _finish(proc: subprocess.Popen[bytes]) -> None:
    assert proc.stdin is not None
    proc.stdin.close()
    assert proc.wait(timeout=10) == 0, proc.stderr.read().decode() if proc.stderr else ""


@pytest.fixture
def running_server(qtbot: QtBot) -> str:
    name = f"pv-host-test-{uuid.uuid4().hex}"
    bridge = BridgeServer(Backend(), Pairing())
    assert bridge.listen(name)
    yield name
    bridge.close()


def test_host_relays_a_framed_request_and_reply(qtbot: QtBot, running_server: str) -> None:
    proc = _start_host(running_server)
    try:
        reply = json.loads(
            _exchange_pumped(qtbot, proc, _request("hello", {"extension_version": "1.0"}))
        )
        assert reply["ok"] is True
        assert reply["result"]["app_version"] == "1.2.3"
    finally:
        _finish(proc)


def test_same_host_process_answers_a_second_request(qtbot: QtBot, running_server: str) -> None:
    proc = _start_host(running_server)
    try:
        first = json.loads(
            _exchange_pumped(qtbot, proc, _request("hello", {"extension_version": "1.0"}))
        )
        assert first["ok"] is True
        second = json.loads(
            _exchange_pumped(qtbot, proc, _request("hello", {"extension_version": "2.0"}))
        )
        assert second["ok"] is True
    finally:
        _finish(proc)


def test_the_host_reconnects_when_the_app_restarts(qtbot: QtBot) -> None:
    """A request that never left the host side may be retried on a fresh
    connection; one the app already answered is never resent (so a save can
    only ever be applied once)."""
    name = f"pv-host-test-{uuid.uuid4().hex}"
    first = BridgeServer(Backend(), Pairing())
    assert first.listen(name)
    proc = _start_host(name)
    try:
        hello = json.loads(
            _exchange_pumped(qtbot, proc, _request("hello", {"extension_version": "1.0"}))
        )
        assert hello["ok"] is True

        first.close()  # the app quits, leaving the host's connection stale
        second = BridgeServer(Backend(), Pairing())
        assert second.listen(name)  # ... and comes back on the same socket
        try:
            again = json.loads(
                _exchange_pumped(qtbot, proc, _request("hello", {"extension_version": "1.0"}))
            )
            assert again["ok"] is True, "the host must retry on a fresh connection"
        finally:
            second.close()
    finally:
        _finish(proc)
    # the two servers hold Qt objects in a reference cycle: collect them here,
    # where no event loop is running, not in the next test's loop
    del first, second
    gc.collect()


def test_host_answers_app_not_running_without_a_server(qtbot: QtBot) -> None:
    proc = _start_host(f"pv-host-test-nothing-{uuid.uuid4().hex}")
    try:
        reply = json.loads(
            _exchange_pumped(qtbot, proc, _request("hello", {"extension_version": "1.0"}))
        )
        assert reply["ok"] is False
        assert reply["error"] == {"code": "app_not_running"}
    finally:
        _finish(proc)


def test_oversized_declared_length_gets_too_large_and_host_stays_usable(
    qtbot: QtBot, running_server: str
) -> None:
    proc = _start_host(running_server)
    try:
        oversized = struct.pack("=I", MAX_REQUEST_BYTES + 1) + b"x" * (MAX_REQUEST_BYTES + 1)
        reply = json.loads(_send_and_recv_pumped(qtbot, proc, oversized))
        assert reply["ok"] is False
        assert reply["error"] == {"code": "too_large"}

        # the host re-synced and answers the next request normally
        hello = json.loads(
            _exchange_pumped(qtbot, proc, _request("hello", {"extension_version": "1.0"}))
        )
        assert hello["ok"] is True
    finally:
        _finish(proc)


def test_the_default_socket_name_matches_the_server_constant() -> None:
    assert SOCKET_NAME == "personal-vault-bridge"
