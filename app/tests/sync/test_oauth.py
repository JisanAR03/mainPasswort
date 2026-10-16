"""M5-01: sign in with Google, and the token's round trip through the vault."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials
from personal_vault import services
from personal_vault.bridge.pairing import PAIRING_ENTRY
from personal_vault.core.models import SecretStr
from personal_vault.core.vault import VaultSession
from personal_vault.sync import oauth
from personal_vault.sync.errors import (
    ClientSecretMissing,
    NetworkError,
    NotLinked,
    ReconnectRequired,
    TokenScopeError,
)
from personal_vault.sync.oauth import DRIVE_SCOPE, GoogleAccount, load_client_config

pytestmark = pytest.mark.sync

CLIENT_ID = "1234567890-example.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-super-secret-client-value"
REFRESH_TOKEN = "1//0g-super-secret-refresh-token"
ACCESS_TOKEN = "ya29.super-secret-access-token"

CONFIG: dict[str, Any] = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}


def _client_secret_file(tmp_path: Path, config: dict[str, Any] | None = None) -> Path:
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps(CONFIG if config is None else config), encoding="utf-8")
    return path


def _credentials(**overrides: Any) -> Credentials:
    values: dict[str, Any] = {
        "token": ACCESS_TOKEN,
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": [DRIVE_SCOPE],
    }
    values.update(overrides)
    return Credentials(**values)


class _FakeFlow:
    """The real flow needs a browser and Google; this one records how it was run."""

    def __init__(self, credentials: Credentials) -> None:
        self.credentials = credentials
        self.kwargs: dict[str, Any] = {}

    def run_local_server(self, **kwargs: Any) -> Credentials:
        self.kwargs = kwargs
        return self.credentials


# --- the flow -------------------------------------------------------------


def test_the_flow_asks_for_drive_file_only_with_pkce_and_a_loopback_redirect() -> None:
    flow = oauth.build_flow(CONFIG)
    url, _ = flow.authorization_url()
    params = parse_qs(urlparse(url).query)
    assert params["scope"] == [DRIVE_SCOPE]  # and nothing else: no drive, no userinfo
    assert params["code_challenge_method"] == ["S256"]  # PKCE
    assert params["code_challenge"][0]
    assert params["access_type"] == ["offline"]  # so a refresh token comes back


def test_connect_runs_the_flow_on_an_ephemeral_localhost_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _FakeFlow(_credentials())
    monkeypatch.setattr(oauth, "build_flow", lambda config: flow)
    account = oauth.connect(CONFIG, email_lookup=lambda token: "owner@example.com")
    assert flow.kwargs["port"] == 0  # the OS picks a free loopback port
    assert flow.kwargs["prompt"] == "consent"  # without it Google may skip the refresh token
    assert account.refresh_token.reveal() == REFRESH_TOKEN
    assert account.email == "owner@example.com"


def test_a_token_minted_for_another_scope_is_refused() -> None:
    with pytest.raises(TokenScopeError):
        oauth.account_from_credentials(
            _credentials(scopes=["https://www.googleapis.com/auth/drive"])
        )


def test_a_broader_token_is_refused_too() -> None:
    with pytest.raises(TokenScopeError):
        oauth.account_from_credentials(
            _credentials(scopes=[DRIVE_SCOPE, "https://www.googleapis.com/auth/drive"])
        )


def test_credentials_without_a_refresh_token_ask_for_a_new_sign_in() -> None:
    with pytest.raises(ReconnectRequired):
        oauth.account_from_credentials(_credentials(refresh_token=None))


# --- refreshing -----------------------------------------------------------


def test_a_refresh_returns_a_fresh_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_refresh(credentials: Credentials) -> None:
        credentials.token = "ya29.refreshed"

    monkeypatch.setattr(oauth, "_refresh", fake_refresh)
    account = GoogleAccount(refresh_token=SecretStr(REFRESH_TOKEN))
    assert oauth.refreshed_access_token(account, CONFIG) == "ya29.refreshed"


def test_invalid_grant_asks_for_a_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(credentials: Credentials) -> None:
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(oauth, "_refresh", refused)
    account = GoogleAccount(refresh_token=SecretStr(REFRESH_TOKEN))
    with pytest.raises(ReconnectRequired) as caught:
        oauth.refreshed_access_token(account, CONFIG)
    assert REFRESH_TOKEN not in str(caught.value)
    assert CLIENT_SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "boom",
    [RefreshError("500 internal error"), TransportError("connection reset by peer")],
)
def test_any_other_refresh_failure_is_retryable(
    monkeypatch: pytest.MonkeyPatch, boom: Exception
) -> None:
    def broken(credentials: Credentials) -> None:
        raise boom

    monkeypatch.setattr(oauth, "_refresh", broken)
    account = GoogleAccount(refresh_token=SecretStr(REFRESH_TOKEN))
    with pytest.raises(NetworkError) as caught:
        oauth.refreshed_access_token(account, CONFIG)
    assert REFRESH_TOKEN not in str(caught.value)


def test_no_token_or_secret_reaches_a_log(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(credentials: Credentials) -> None:
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(oauth, "_refresh", refused)
    account = GoogleAccount(refresh_token=SecretStr(REFRESH_TOKEN))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ReconnectRequired):
            oauth.refreshed_access_token(account, CONFIG)
    assert REFRESH_TOKEN not in repr(account)  # a dataclass repr must not reveal it
    for secret in (REFRESH_TOKEN, CLIENT_SECRET, ACCESS_TOKEN):
        assert secret not in caplog.text


# --- client_secret.json ---------------------------------------------------


def test_a_missing_client_secret_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ClientSecretMissing):
        load_client_config(tmp_path / "client_secret.json")


def test_an_unreadable_client_secret_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "client_secret.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ClientSecretMissing):
        load_client_config(path)


def test_a_client_secret_file_without_an_installed_client_is_reported(tmp_path: Path) -> None:
    path = _client_secret_file(tmp_path, {"web": CONFIG["installed"]})
    with pytest.raises(ClientSecretMissing):
        load_client_config(path)


def test_a_client_secret_file_is_read(tmp_path: Path) -> None:
    config = load_client_config(_client_secret_file(tmp_path))
    assert config["installed"]["client_id"] == CLIENT_ID


# --- the token in the vault -----------------------------------------------


def _open(tmp_path: Path) -> VaultSession:
    """Open the test vault (building it once: building again would wipe it)."""
    vault_path = tmp_path / "vault.kdbx"
    if not vault_path.exists():
        build_weak_vault(vault_path)
    return VaultSession.open(vault_path, WEAK_PASSWORD, tmp_path / "backups")


def test_the_token_round_trips_through_the_vault(tmp_path: Path) -> None:
    account = GoogleAccount(refresh_token=SecretStr(REFRESH_TOKEN), email="owner@example.com")
    session = _open(tmp_path)
    services.save_google_account(session, account)
    services.save_vault(session)
    session.close()  # lock

    unlocked = _open(tmp_path)  # unlock
    try:
        loaded = services.google_account(unlocked)
    finally:
        unlocked.close()
    assert loaded is not None
    assert loaded.refresh_token.reveal() == REFRESH_TOKEN
    assert loaded.email == "owner@example.com"


def test_a_profile_that_never_signed_in_has_no_account(tmp_path: Path) -> None:
    session = _open(tmp_path)
    try:
        assert services.google_account(session) is None
        with pytest.raises(NotLinked):
            services.google_access_token(session)
    finally:
        session.close()


def test_disconnect_deletes_its_entry_and_nothing_else(tmp_path: Path) -> None:
    session = _open(tmp_path)
    try:
        session.add(
            make_login(title="Local Dev", username="dev@example.com", password=SecretStr("pw"))
        )
        session.set_app_value(PAIRING_ENTRY, "ABCDEF")
        services.save_google_account(session, GoogleAccount(refresh_token=SecretStr(REFRESH_TOKEN)))

        services.disconnect_google(session)

        assert services.google_account(session) is None
        assert session.get_app_value(PAIRING_ENTRY) == "ABCDEF"  # the browser key is untouched
        assert [summary.title for summary in session.list_logins()] == ["Local Dev"]
        assert session.get(session.list_logins()[0].id).password.reveal() == "pw"
        # and the refresh token is gone from the bytes on disk, not just from view
        services.save_vault(session)
    finally:
        session.close()
    assert REFRESH_TOKEN.encode() not in (tmp_path / "vault.kdbx").read_bytes()
