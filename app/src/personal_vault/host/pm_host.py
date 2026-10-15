"""The native messaging host the browser starts ([S]).

Chrome/Brave launch this process (once per extension port) and talk to it over
stdio with native-messaging framing: a 4-byte native-order length prefix, then
UTF-8 JSON. The host holds nothing: it reads one framed request, forwards it to
the app's local socket, and writes the framed reply back. It never touches the
vault and never reads the request body (the app validates everything).

The socket name defaults to protocol.SOCKET_NAME and can be overridden with the
PERSONAL_VAULT_SOCKET environment variable (used by tests; the installer writes
launchers that leave it unset).
"""

from __future__ import annotations

import os
import socket
import struct
import sys
from typing import IO, cast

from personal_vault.bridge.protocol import (
    MAX_REPLY_BYTES,
    MAX_REQUEST_BYTES,
    SOCKET_NAME,
    frame,
    reply,
)


def socket_name() -> str:
    return os.environ.get("PERSONAL_VAULT_SOCKET", SOCKET_NAME)


def _connect() -> IO[bytes]:
    """Open the app's local socket; OSError when the app is not running.

    Qt's QLocalServer listens on a named pipe ``<name>`` on Windows and on the
    socket file ``<TMPDIR>/<name>`` elsewhere — the same rule QLocalServer
    uses for names without a slash.
    """
    if os.name == "nt":
        return open("\\\\.\\pipe\\" + socket_name(), "rb+", buffering=0)
    # /tmp is not an arbitrary temp choice: QLocalServer puts socket files in
    # <TMPDIR>/<name>, and the host must connect exactly there
    path = os.path.join(os.environ.get("TMPDIR", "/tmp"), socket_name())  # nosec B108
    # getattr, not attribute access: AF_UNIX is missing from the Windows
    # typeshed stubs (it exists at runtime), so direct access needs a
    # platform-dependent type: ignore that Linux mypy rejects as unused
    sock = socket.socket(getattr(socket, "AF_UNIX"), socket.SOCK_STREAM)  # noqa: B009
    sock.connect(path)
    return cast(IO[bytes], sock.makefile("rwb", buffering=0))


def _read_exact(stream: IO[bytes], length: int) -> bytes | None:
    chunks = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            return None  # EOF: the browser closed the port
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write(stream: IO[bytes], raw: bytes) -> None:
    stream.write(raw)
    stream.flush()


def _relay(stdin: IO[bytes], stdout: IO[bytes]) -> int:
    app: IO[bytes] | None = None
    while True:
        header = _read_exact(stdin, 4)
        if header is None:
            return 0
        (length,) = struct.unpack("=I", header)
        if length > MAX_REQUEST_BYTES:
            # refuse without parsing; discard the body so the stream stays in sync
            _write(stdout, frame(reply("", ok=False, error_code="too_large")))
            if _read_exact(stdin, length) is None:
                return 0
            continue
        body = _read_exact(stdin, length)
        if body is None:
            return 0
        if app is None:
            try:
                app = _connect()
            except OSError:
                _write(stdout, frame(reply("", ok=False, error_code="app_not_running")))
                continue
        try:
            _write(app, frame(body))
            header = _read_exact(app, 4)
            if header is None:
                raise OSError("the app closed the socket")
            (reply_length,) = struct.unpack("=I", header)
            if reply_length > MAX_REPLY_BYTES:
                raise OSError("reply exceeds the protocol cap")
            reply_body = _read_exact(app, reply_length)
            if reply_body is None:
                raise OSError("the app closed the socket mid-reply")
        except OSError:
            app = None  # the app went away; reconnect for the next request
            _write(stdout, frame(reply("", ok=False, error_code="app_not_running")))
            continue
        # the app's framing is transport-level: stdio carries one frame holding
        # just the JSON reply
        _write(stdout, frame(reply_body))


def run(stdin: IO[bytes] | None = None, stdout: IO[bytes] | None = None) -> None:
    """The host main loop; raises SystemExit(0) when stdin closes."""
    code = _relay(
        sys.stdin.buffer if stdin is None else stdin,
        sys.stdout.buffer if stdout is None else stdout,
    )
    raise SystemExit(code)


if __name__ == "__main__":
    run()
