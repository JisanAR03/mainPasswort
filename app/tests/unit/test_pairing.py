"""M3-03: pairing key validation, the 6-character code and the 60-second window."""

from __future__ import annotations

import base64

import pytest
from personal_vault.bridge.pairing import (
    CODE_ALPHABET,
    CODE_LENGTH,
    PAIR_TIMEOUT_SECONDS,
    PAIRING_ENTRY,
    Pairing,
    pairing_code,
)

pytestmark = pytest.mark.unit

KEY = base64.b64encode(bytes(range(32))).decode()
OTHER_KEY = base64.b64encode(bytes(range(32, 64))).decode()


class FakeSession:
    """The two vault methods pairing uses, in memory."""

    def __init__(self, stored: str | None = None) -> None:
        self.stored = stored
        self.saved = 0

    def get_app_value(self, name: str) -> str | None:
        assert name == PAIRING_ENTRY
        return self.stored

    def set_app_value(self, name: str, value: str) -> None:
        self.stored = value

    def save(self) -> None:
        self.saved += 1


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_pairing(
    session: FakeSession | None = None,
    confirm: bool = True,
    clock: Clock | None = None,
) -> tuple[Pairing, list[tuple[str, str]]]:
    shown: list[tuple[str, str]] = []

    def dialog(browser_name: str, code: str) -> bool:
        shown.append((browser_name, code))
        return confirm

    target = FakeSession() if session is None else session
    return Pairing(target, dialog, now=clock or Clock()), shown


def test_pairing_code_is_six_alphabet_characters() -> None:
    for raw in (b"\x00" * 32, bytes(range(32)), KEY.encode()):
        code = pairing_code(raw)
        assert len(code) == CODE_LENGTH
        assert set(code) <= set(CODE_ALPHABET)


def test_pairing_code_differs_between_keys() -> None:
    codes = {pairing_code(base64.b64decode(k)) for k in (KEY, OTHER_KEY)}
    assert len(codes) == 2


def test_malformed_keys_are_refused_without_a_dialog() -> None:
    pairing, shown = make_pairing()
    malformed = [
        "",
        "short",
        "a" * 44,  # valid base64 but 33 bytes, not 32
        base64.b64encode(b"\x00" * 16).decode(),  # 24 chars: wrong length
        "=" * 44,
        KEY[:-1] + "!",  # right length, invalid base64
    ]
    for key in malformed:
        assert pairing.accept(key, "Chrome") is False, key
    assert shown == []


def test_pair_click_stores_the_key_in_the_vault() -> None:
    session = FakeSession()
    pairing, shown = make_pairing(session)
    assert pairing.accept(KEY, "Chrome") is True
    assert session.stored == KEY
    assert session.saved == 1
    assert pairing.key_valid(KEY) is True
    assert pairing.key_valid(OTHER_KEY) is False
    assert shown == [("Chrome", pairing_code(base64.b64decode(KEY)))]


def test_cancel_stores_nothing() -> None:
    session = FakeSession()
    pairing, _ = make_pairing(session, confirm=False)
    assert pairing.accept(KEY, "Chrome") is False
    assert session.stored is None
    assert session.saved == 0


def test_same_key_accepts_without_a_second_dialog() -> None:
    session = FakeSession(stored=KEY)
    pairing, shown = make_pairing(session)
    assert pairing.accept(KEY, "Chrome") is True
    assert shown == []
    assert session.saved == 0


def test_second_key_needs_the_dialog_and_replaces() -> None:
    session = FakeSession(stored=KEY)
    pairing, shown = make_pairing(session)
    assert pairing.accept(OTHER_KEY, "Brave") is True
    assert session.stored == OTHER_KEY
    assert pairing.key_valid(KEY) is False
    assert pairing.key_valid(OTHER_KEY) is True
    assert shown[0][0] == "Brave"


def test_second_key_rejected_keeps_the_old_key() -> None:
    session = FakeSession(stored=KEY)
    pairing, _ = make_pairing(session, confirm=False)
    assert pairing.accept(OTHER_KEY, "Brave") is False
    assert session.stored == KEY
    assert pairing.key_valid(KEY) is True


def test_confirm_after_the_window_is_refused() -> None:
    clock = Clock()
    session = FakeSession()

    def slow_confirm(browser_name: str, code: str) -> bool:
        clock.advance(PAIR_TIMEOUT_SECONDS + 1)
        return True

    pairing = Pairing(session, slow_confirm, now=clock)
    assert pairing.accept(KEY, "Chrome") is False
    assert session.stored is None
    assert session.saved == 0


def test_without_an_unlocked_vault_a_new_key_cannot_pair() -> None:
    shown: list[tuple[str, str]] = []
    pairing = Pairing(None, lambda browser, code: shown.append((browser, code)) or True)
    assert pairing.accept(KEY, "Chrome") is False
    assert shown == []
    assert pairing.key_valid(KEY) is False
    # even the stored key cannot be read while the vault is locked
    session = FakeSession(stored=KEY)
    pairing, shown2 = make_pairing(session)
    pairing.set_session(None)
    assert pairing.key_valid(KEY) is False
    assert pairing.accept(OTHER_KEY, "Chrome") is False
    assert shown2 == []
    assert session.stored == KEY  # nothing changed while locked
