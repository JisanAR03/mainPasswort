"""A real bridge process over a weak test vault, for the e2e suite.

Started by the tests with PV_VAULT_PATH, PV_VAULT_PASSWORD, PV_BRIDGE_SOCKET
and PV_BACKUPS_DIR (and PV_START_LOCKED=1 for the locked-vault case); prints
READY once the socket is listening, then runs the Qt event loop. Each
show_unlock request appends a line to PV_UNLOCK_MARKER, where the desktop app
would bring its unlock window forward.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from personal_vault.bridge.backend import VaultBackend
from personal_vault.bridge.pairing import Pairing
from personal_vault.bridge.server import BridgeServer
from personal_vault.core.vault import VaultSession
from PySide6.QtCore import QCoreApplication

PROFILE_NAME = "E2E"


def _confirm(browser_name: str, code: str) -> bool:
    """Always pair, as the desktop app's dialog would after a click.

    PV_PAIR_DELAY_MS holds the answer back for a moment so a test can read the
    code the popup shows while the app is still waiting for its click.
    """
    delay_ms = int(os.environ.get("PV_PAIR_DELAY_MS", "0"))
    if delay_ms:
        time.sleep(delay_ms / 1000)
    return True


def _show_unlock() -> None:
    marker = os.environ.get("PV_UNLOCK_MARKER")
    if marker:
        with open(marker, "a", encoding="utf-8") as log:
            log.write("show_unlock\n")


def main() -> int:
    app = QCoreApplication([])
    session = None
    if os.environ.get("PV_START_LOCKED") != "1":
        session = VaultSession.open(
            Path(os.environ["PV_VAULT_PATH"]),
            os.environ["PV_VAULT_PASSWORD"],
            Path(os.environ["PV_BACKUPS_DIR"]),
        )
    backend = VaultBackend(session, PROFILE_NAME, show_unlock=_show_unlock)
    pairing = Pairing(session, confirm=_confirm)
    server = BridgeServer(backend, pairing)
    if not server.listen(os.environ["PV_BRIDGE_SOCKET"]):
        print("LISTEN-FAILED", flush=True)
        return 1
    print("READY", flush=True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
