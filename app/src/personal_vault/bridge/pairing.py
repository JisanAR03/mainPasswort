"""Pairing: the 6-character code both sides show, and the 60-second pair flow ([S]).

The extension's `pair_request` carries a fresh 32-byte key (base64). We derive a
6-character code from it that the extension derives the same way, show a
confirmation dialog, and only store the key in the vault (hidden `.app` group,
`browser-pairing`) when the user clicks Pair inside the 60-second window. From
then on that key passes ``key_valid`` and no other key does.

Pure Python: the dialog arrives as a callback, so everything here is testable
without Qt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Callable

from personal_vault.core.errors import VaultError
from personal_vault.core.vault import VaultSession

PAIRING_ENTRY = "browser-pairing"
PAIR_TIMEOUT_SECONDS = 60.0
CODE_LENGTH = 6
# 32 characters with no easily-confused pairs (no 0/O/1/I).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def pairing_code(key: bytes) -> str:
    """The code both sides show, derived deterministically from the raw key.

    SHA-256 over the 32 key bytes; each of the first six digest bytes picks one
    of 32 alphabet characters (byte % 32). Reproducible in the extension's
    JavaScript for M4.
    """
    digest = hashlib.sha256(key).digest()
    return "".join(CODE_ALPHABET[b % len(CODE_ALPHABET)] for b in digest[:CODE_LENGTH])


def _decode_key(key: str) -> bytes | None:
    """The canonical form of a pairing key: base64 of exactly 32 bytes."""
    if len(key) != 44:
        return None
    try:
        raw = base64.b64decode(key.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        return None
    return raw if len(raw) == 32 else None


class Pairing:
    """Implements the Pairing protocol against the key stored in the vault."""

    def __init__(
        self,
        session: VaultSession | None,
        confirm: Callable[[str, str], bool],
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session
        self._confirm = confirm  # (browser_name, code) -> clicked Pair
        self._now = now

    def set_session(self, session: VaultSession | None) -> None:
        """Swap the session on unlock/lock; the stored key lives in the vault."""
        self._session = session

    def key_valid(self, key: str) -> bool:
        stored = self._stored_key()
        return stored is not None and hmac.compare_digest(stored, key)

    def accept(self, key: str, browser_name: str) -> bool:
        stored = self._stored_key()
        if stored is not None and hmac.compare_digest(stored, key):
            return True  # the paired browser reconnecting: no dialog
        raw = _decode_key(key)
        if raw is None:
            return False  # not a well-formed key; never show a dialog for it
        session = self._session
        if session is None:
            return False  # pairing stores the key in the vault; unlock first
        deadline = self._now() + PAIR_TIMEOUT_SECONDS
        if not self._confirm(browser_name, pairing_code(raw)):
            return False
        if self._now() > deadline:
            return False  # the click came after the 60-second window
        try:
            session.set_app_value(PAIRING_ENTRY, key)
            session.save()
        except VaultError:
            return False
        return True

    def _stored_key(self) -> str | None:
        session = self._session
        if session is None:
            return None
        try:
            return session.get_app_value(PAIRING_ENTRY)
        except VaultError:
            return None
