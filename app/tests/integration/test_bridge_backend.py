"""M3-01: VaultBackend over a real (weak-KDF) vault — matching, secrets, saves."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, make_login
from personal_vault import __version__
from personal_vault.bridge.backend import GENERATE_DEFAULT_LENGTH, VaultBackend
from personal_vault.bridge.protocol import UrlMismatchError
from personal_vault.core.models import SecretStr
from personal_vault.core.vault import VaultSession

pytestmark = pytest.mark.integration

PROFILE = "Test Profile"
URL = "https://example.com/login"


def backend_for(session: VaultSession) -> VaultBackend:
    return VaultBackend(session, PROFILE, show_unlock=lambda: None)


def test_app_info_and_unlocked_follow_the_session(weak_session: VaultSession) -> None:
    backend = backend_for(weak_session)
    assert backend.unlocked() is True
    assert backend.app_info() == (__version__, PROFILE)
    weak_session.close()
    assert backend.unlocked() is False


def test_matching_logins_uses_the_site_matching_rules(weak_session: VaultSession) -> None:
    weak_session.add(make_login(title="Match", urls=["https://example.com"]))
    weak_session.add(make_login(title="No Match", urls=["https://other.org"]))
    weak_session.save()
    matches = backend_for(weak_session).matching_logins(URL)
    assert [m.title for m in matches] == ["Match"]


def test_secret_for_returns_none_on_unknown_entry(weak_session: VaultSession) -> None:
    backend = backend_for(weak_session)
    assert backend.secret_for(str(uuid.uuid4()), URL) is None
    assert backend.secret_for("not-a-uuid", URL) is None


def test_save_login_persists_a_new_entry(weak_session: VaultSession, tmp_path: Path) -> None:
    backend = backend_for(weak_session)
    entry_id = backend.save_login(URL, "user@example.com", SecretStr("new-password"), "Saved")
    weak_session.close()

    with VaultSession.open(weak_session.path, WEAK_PASSWORD, tmp_path / "backups") as reopened:
        login = reopened.get(uuid.UUID(entry_id))
        assert login.title == "Saved"
        assert login.username == "user@example.com"
        assert login.password.reveal() == "new-password"
        assert login.urls == [URL]


def test_update_password_changes_only_the_matching_entry(
    weak_session: VaultSession, tmp_path: Path
) -> None:
    entry = make_login(password=SecretStr("old-password"), urls=["https://example.com"])
    weak_session.add(entry)
    weak_session.save()
    backend = backend_for(weak_session)
    backend.update_password(str(entry.id), URL, SecretStr("new-password"))
    weak_session.close()

    with VaultSession.open(weak_session.path, WEAK_PASSWORD, tmp_path / "backups") as reopened:
        assert reopened.get(entry.id).password.reveal() == "new-password"


def test_update_password_refuses_a_nonmatching_url(weak_session: VaultSession) -> None:
    entry = make_login(password=SecretStr("old-password"), urls=["https://example.com"])
    weak_session.add(entry)
    weak_session.save()
    with pytest.raises(UrlMismatchError):
        backend_for(weak_session).update_password(
            str(entry.id), "https://evil.com", SecretStr("attacker")
        )
    assert weak_session.get(entry.id).password.reveal() == "old-password"


def test_generate_respects_length_and_default(weak_session: VaultSession) -> None:
    backend = backend_for(weak_session)
    generated = backend.generate(24)
    assert len(generated) == 24
    assert len(backend.generate(None)) == GENERATE_DEFAULT_LENGTH


def test_lock_closes_the_session(weak_session: VaultSession) -> None:
    backend = backend_for(weak_session)
    backend.lock()
    assert backend.unlocked() is False
