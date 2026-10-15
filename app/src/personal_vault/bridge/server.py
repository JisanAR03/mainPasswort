"""The local socket server the native host relays to ([S]).

Listens on a Qt local socket (a named pipe on Windows, a Unix socket
elsewhere) restricted to the current OS user, frames every message with the
native-messaging 4-byte length prefix, and dispatches it through the M3-01
Dispatcher. ``get_secret`` is rate-limited to 10 per minute per pairing key
(browser-protocol.md), enforced by a token bucket shared across connections.
"""

from __future__ import annotations

import struct
import time
from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from shiboken6 import isValid

from personal_vault.bridge.protocol import (
    MAX_REQUEST_BYTES,
    BridgeBackend,
    Dispatcher,
    Pairing,
    frame,
    reply,
)

DEFAULT_SECRET_CAPACITY = 10
DEFAULT_SECRET_PER_SECOND = 10 / 60


class TokenBucket:
    """Refills ``capacity`` tokens at ``tokens_per_second``; one bucket per key."""

    def __init__(
        self,
        capacity: int,
        tokens_per_second: float,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity = capacity
        self._rate = tokens_per_second
        self._now = now
        self._state: dict[str, tuple[float, float]] = {}

    def take(self, key: str) -> bool:
        stamp = self._now()
        tokens, last = self._state.get(key, (float(self._capacity), stamp))
        tokens = min(float(self._capacity), tokens + (stamp - last) * self._rate)
        if tokens < 1.0:
            self._state[key] = (tokens, stamp)
            return False
        self._state[key] = (tokens - 1.0, stamp)
        return True


class _Connection(QObject):
    """One client connection: reassembles frames and writes one reply each."""

    def __init__(self, server: BridgeServer, socket: QLocalSocket) -> None:
        super().__init__(server)
        self._server = server
        self._socket = socket
        self._buffer = b""
        socket.readyRead.connect(self._on_ready_read)
        socket.disconnected.connect(self._on_disconnected)

    def _on_ready_read(self) -> None:
        self._buffer += self._socket.readAll().data()
        self._process()

    def _process(self) -> None:
        while True:
            if len(self._buffer) < 4:
                return
            (length,) = struct.unpack_from("=I", self._buffer)
            if length > MAX_REQUEST_BYTES:
                # refuse without reading the body; the stream cannot be re-synced
                self._socket.write(frame(reply("", ok=False, error_code="too_large")))
                self._socket.flush()
                self._socket.disconnectFromServer()
                return
            if len(self._buffer) < 4 + length:
                return
            request = self._buffer[4 : 4 + length]
            self._buffer = self._buffer[4 + length :]
            self._socket.write(frame(self._server.dispatcher.dispatch(request)))
            self._socket.flush()

    def _on_disconnected(self) -> None:
        self._server._connections.discard(self)  # noqa: SLF001 - same-module hook
        if isValid(self._socket):  # teardown order can delete it first
            self._socket.deleteLater()
        self.deleteLater()

    def abort(self) -> None:
        self._socket.abort()


class BridgeServer(QObject):
    """A QLocalServer with the bridge dispatcher behind it."""

    def __init__(
        self,
        backend: BridgeBackend,
        pairing: Pairing,
        secret_bucket: TokenBucket | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        bucket = secret_bucket or TokenBucket(DEFAULT_SECRET_CAPACITY, DEFAULT_SECRET_PER_SECOND)
        self.dispatcher = Dispatcher(backend, pairing, secret_allowed=bucket.take)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._on_new_connection)
        self._connections: set[_Connection] = set()

    def listen(self, name: str) -> bool:
        """Listen on ``name``; clears a stale socket only if the name is taken."""
        if self.server.listen(name):
            return True
        QLocalServer.removeServer(name)
        return self.server.listen(name)

    def _on_new_connection(self) -> None:
        while self.server.hasPendingConnections():
            self._connections.add(_Connection(self, self.server.nextPendingConnection()))

    def close(self) -> None:
        for connection in list(self._connections):
            connection.abort()
        self._connections.clear()
        self.server.close()
