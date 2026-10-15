"""VaultBackend: the bridge's only door to the vault (M3-01).

Implements bridge.protocol.BridgeBackend over a VaultSession plus the matching
rules, so protocol.py stays pure and every bridge operation the spec allows is
backed by the tested core. Invariant I4 lives here: a secret is only ever
returned when the entry's URLs match the requesting tab.

The session may be None (vault locked or not opened yet): then ``unlocked()``
is False and every vault operation is refused, which the dispatcher turns into
``locked`` replies (I5). The app swaps the session in on unlock and out on lock.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from personal_vault import __version__
from personal_vault.bridge.protocol import UrlMismatchError
from personal_vault.core.errors import VaultError
from personal_vault.core.generator import generate_password
from personal_vault.core.matching import match_urls
from personal_vault.core.models import LoginEntry, LoginSummary, SecretStr
from personal_vault.core.vault import VaultSession

GENERATE_DEFAULT_LENGTH = 20


class VaultBackend:
    """Adapts an open VaultSession to the BridgeBackend protocol."""

    def __init__(
        self,
        session: VaultSession | None,
        profile_name: str,
        show_unlock: Callable[[], None],
    ) -> None:
        self._session = session
        self._profile_name = profile_name
        self._show_unlock = show_unlock

    def set_session(self, session: VaultSession | None) -> None:
        """Swap the session in on unlock and out on lock."""
        self._session = session

    def set_profile(self, profile_name: str) -> None:
        self._profile_name = profile_name

    def unlocked(self) -> bool:
        session = self._session
        if session is None:
            return False
        try:
            _ = session._open_kp  # raises VaultError once the vault is closed
        except VaultError:
            return False
        return True

    def _open_session(self) -> VaultSession:
        session = self._session
        if session is None:
            raise VaultError("vault is closed")
        return session

    def app_info(self) -> tuple[str, str]:
        return __version__, self._profile_name

    def matching_logins(self, url: str) -> list[LoginSummary]:
        return self._open_session().matching_logins(url)

    def secret_for(self, entry_id: str, url: str) -> tuple[str, SecretStr] | None:
        session = self._session
        if session is None:
            return None
        try:
            parsed_id = uuid.UUID(entry_id)
        except ValueError:
            return None
        try:
            login = session.get(parsed_id)
        except (KeyError, ValueError, VaultError):
            return None
        if not match_urls(login.urls, url, match_subdomains=login.match_subdomains):
            return None  # I4: never the password for a non-matching URL
        return login.username, login.password

    def save_login(self, url: str, username: str, password: SecretStr, title: str | None) -> str:
        session = self._open_session()
        now = datetime.now(UTC)
        entry = LoginEntry(
            id=uuid.uuid4(),
            title=title or url,
            username=username,
            password=password,
            urls=[url],
            notes="",
            tags=[],
            match_subdomains=False,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.save()
        return str(entry.id)

    def update_password(self, entry_id: str, url: str, new_password: SecretStr) -> None:
        session = self._open_session()
        try:
            parsed_id = uuid.UUID(entry_id)
        except ValueError:
            raise UrlMismatchError from None
        login = session.get(parsed_id)
        if not match_urls(login.urls, url, match_subdomains=login.match_subdomains):
            raise UrlMismatchError  # I4
        session.edit(
            dataclasses.replace(login, password=new_password, updated_at=datetime.now(UTC))
        )
        session.save()

    def generate(self, length: int | None) -> str:
        return generate_password(length or GENERATE_DEFAULT_LENGTH).reveal()

    def lock(self) -> None:
        if self._session is not None:
            self._session.close()

    def show_unlock(self) -> None:
        self._show_unlock()
