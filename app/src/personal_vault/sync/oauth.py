"""Sign in with Google for ``drive.file`` alone ([S]: everything here is a token path).

A Desktop-app OAuth client, a loopback redirect and PKCE, exactly as
docs/specs/sync.md describes. The refresh token is handed back to the caller
inside a ``SecretStr`` and is stored in the profile's vault by services.py;
this module never writes a file and never logs, so no token can reach a
plaintext file, a log record or an error message.

``client_secret.json`` is the owner's own Google Cloud client, git-ignored
(docs/setup-google-drive.md walks through making one).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from personal_vault.core.models import SecretStr
from personal_vault.sync.errors import (
    ClientSecretMissing,
    NetworkError,
    ReconnectRequired,
    TokenScopeError,
)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
SCOPES = [DRIVE_SCOPE]
DRIVE_SYNC_ENTRY = "drive-sync"
# The owner's own OAuth client; the file itself is git-ignored, this is only
# its name in the data folder
CLIENT_CONFIG_FILE = "client_secret.json"


@dataclass(frozen=True)
class GoogleAccount:
    """What the vault keeps: the refresh token, and whose account it is."""

    refresh_token: SecretStr
    email: str | None = None


def load_client_config(path: str | Path) -> Mapping[str, Any]:
    """The owner's OAuth client, or a clear error saying what to do about it."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise ClientSecretMissing(
            f"{Path(path).name} is missing or unreadable; see docs/setup-google-drive.md"
        ) from exc
    installed = raw.get("installed") if isinstance(raw, dict) else None
    if not isinstance(installed, dict) or not installed.get("client_id"):
        raise ClientSecretMissing(
            f"{Path(path).name} is not a Desktop-app client; see docs/setup-google-drive.md"
        )
    return cast("Mapping[str, Any]", raw)


def build_flow(config: Mapping[str, Any]) -> InstalledAppFlow:
    """The installed-app flow for drive.file; it adds PKCE by itself."""
    return InstalledAppFlow.from_client_config(dict(config), SCOPES)


def account_from_credentials(credentials: Credentials) -> GoogleAccount:
    """The account a token grant stands for, refusing anything but drive.file."""
    granted = set(credentials.scopes or ())
    if granted != set(SCOPES):
        raise TokenScopeError("Google returned a token for more than drive.file; connect again")
    refresh_token = credentials.refresh_token
    if not refresh_token:
        raise ReconnectRequired(
            "Google did not return a refresh token; remove this app's access in your "
            "Google account and connect again"
        )
    return GoogleAccount(refresh_token=SecretStr(refresh_token))


def connect(
    config: Mapping[str, Any],
    *,
    email_lookup: Callable[[str], str | None] | None = None,
) -> GoogleAccount:
    """Run the browser sign-in and return the account to store.

    ``prompt="consent"`` is what makes Google hand out a refresh token on every
    sign-in, not only the first; ``port=0`` lets the OS pick a free loopback
    port, so nothing fixed is left listening.
    """
    flow = build_flow(config)
    credentials = flow.run_local_server(port=0, prompt="consent", open_browser=True)
    account = account_from_credentials(credentials)
    if credentials.token and email_lookup is not None:
        account = replace(account, email=email_lookup(credentials.token))
    return account


def _refresh(credentials: Credentials) -> None:
    """The one network call in this module; tests replace it."""
    # google-auth annotates Credentials but not refresh(): the ignore is the
    # library's, not ours
    credentials.refresh(Request())  # type: ignore[no-untyped-call]


def refreshed_access_token(account: GoogleAccount, config: Mapping[str, Any]) -> str:
    """A fresh access token, or an error the UI can act on (sync.md retries)."""
    installed = dict(config.get("installed", {}))
    credentials = Credentials(  # type: ignore[no-untyped-call]
        token=None,
        refresh_token=account.refresh_token.reveal(),
        client_id=installed.get("client_id"),
        client_secret=installed.get("client_secret"),
        token_uri=str(installed.get("token_uri") or "https://oauth2.googleapis.com/token"),
        scopes=SCOPES,
    )
    try:
        _refresh(credentials)
    except RefreshError as exc:
        # Google's own wording is not repeated: the test suite asserts that no
        # error message carries a token, and the UI has its own sentences
        if "invalid_grant" in str(exc):
            raise ReconnectRequired("Google no longer accepts the stored sign-in") from exc
        raise NetworkError("could not reach Google for a new access token") from exc
    except TransportError as exc:
        raise NetworkError("could not reach Google for a new access token") from exc
    token = credentials.token
    if not token:
        raise ReconnectRequired("Google returned no access token; connect again")
    return str(token)
