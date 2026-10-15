"""M3-03: pairing against a real vault — the key lands in the hidden .app group."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, make_login
from personal_vault.bridge.backend import VaultBackend
from personal_vault.bridge.pairing import PAIRING_ENTRY, Pairing
from personal_vault.bridge.protocol import Dispatcher
from personal_vault.core.vault import VaultSession

pytestmark = pytest.mark.integration

KEY = base64.b64encode(bytes(range(32))).decode()
OTHER_KEY = base64.b64encode(bytes(range(32, 64))).decode()


def _pair_request(key: str, browser: str = "Chrome") -> bytes:
    return json.dumps(
        {
            "v": 1,
            "id": "req-pair",
            "type": "pair_request",
            "pairing_key": key,
            "payload": {"key": key, "browser_name": browser},
        }
    ).encode()


def test_pairing_stores_the_key_in_the_vault_app_group(
    weak_session: VaultSession, tmp_path: Path
) -> None:
    pairing = Pairing(weak_session, confirm=lambda browser, code: True)
    assert pairing.accept(KEY, "Chrome") is True
    assert weak_session.get_app_value(PAIRING_ENTRY) == KEY
    assert pairing.key_valid(KEY) is True

    # the key survives a close and reopen: it lives in the vault file itself
    weak_session.close()
    with VaultSession.open(weak_session.path, WEAK_PASSWORD, tmp_path / "backups") as reopened:
        assert reopened.get_app_value(PAIRING_ENTRY) == KEY
        assert Pairing(reopened, confirm=lambda b, c: False).key_valid(KEY) is True


def test_pair_request_through_the_dispatcher_pairs_and_unlocks_logins(
    weak_session: VaultSession, tmp_path: Path
) -> None:
    weak_session.add(make_login(title="Match", urls=["https://example.com"]))
    weak_session.save()
    backend = VaultBackend(weak_session, "Test Profile", show_unlock=lambda: None)
    pairing = Pairing(weak_session, confirm=lambda browser, code: True)
    dispatcher = Dispatcher(backend, pairing)

    reply = json.loads(dispatcher.dispatch(_pair_request(KEY)))
    assert reply["ok"] is True
    assert reply["result"] == {"paired": True}

    logins = json.loads(
        dispatcher.dispatch(
            json.dumps(
                {
                    "v": 1,
                    "id": "req-logins",
                    "type": "get_logins",
                    "pairing_key": KEY,
                    "payload": {"url": "https://example.com/login"},
                }
            ).encode()
        )
    )
    assert logins["ok"] is True
    assert logins["result"]["logins"][0]["title"] == "Match"

    # a second dispatcher on a fresh session reads the stored key from the vault
    weak_session.close()
    with VaultSession.open(weak_session.path, WEAK_PASSWORD, tmp_path / "backups") as reopened:
        reopened_backend = VaultBackend(reopened, "Test Profile", show_unlock=lambda: None)
        reopened_pairing = Pairing(reopened, confirm=lambda b, c: False)
        refused = json.loads(
            Dispatcher(reopened_backend, reopened_pairing).dispatch(
                json.dumps(
                    {
                        "v": 1,
                        "id": "req-logins",
                        "type": "get_logins",
                        "pairing_key": OTHER_KEY,
                        "payload": {"url": "https://example.com/login"},
                    }
                ).encode()
            )
        )
        assert refused["error"] == {"code": "not_paired"}


def test_app_group_round_trip_and_missing_value(weak_session: VaultSession) -> None:
    assert weak_session.get_app_value("does-not-exist") is None
    weak_session.set_app_value("other-app-value", "stored-value")
    weak_session.save()
    assert weak_session.get_app_value("other-app-value") == "stored-value"
    weak_session.set_app_value("other-app-value", "replaced")
    assert weak_session.get_app_value("other-app-value") == "replaced"
