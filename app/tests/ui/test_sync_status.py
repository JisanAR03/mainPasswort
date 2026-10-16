"""M5-06: the sync status line, linking and unlinking, and the interval setting.

Everything here runs against FakeDrive and a vault in a throwaway data dir:
the only thing the fake stands in for is Google, and the one place a token
would be minted for real (the 401-refresh test) patches it out.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault import services
from personal_vault.core.models import SecretStr
from personal_vault.core.vault import VaultSession
from personal_vault.services import (
    Status,
    SyncController,
    SyncResult,
    VaultError,
    google_account,
    list_logins,
    save_vault,
    sync_interval_minutes,
    upload_quiet_seconds,
)
from personal_vault.sync.errors import AuthExpired, NotLinked, ServerError
from personal_vault.sync.fake_drive import FakeDrive
from personal_vault.sync.oauth import GoogleAccount
from personal_vault.ui.settings_dialog import SettingsDialog
from personal_vault.ui.sync_status import ConflictCopyDialog, SyncStatusBar, outcome_of
from personal_vault.ui.vault_view import VaultView
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QMessageBox
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.ui

PROFILE_ID = "p_testprofile"
EMAIL = "owner@example.com"
MARKER = "correct horse battery staple"
CLIENT_CONFIG = {
    "installed": {"client_id": "test.apps.googleusercontent.com", "client_secret": "not-a-secret"}
}


class _Profile:
    """A real profile folder, a vault in it, and a fake Drive."""

    def __init__(self, tmp_path: Path) -> None:
        self.data = tmp_path / "data"
        self.folder = self.data / "profiles" / PROFILE_ID
        self.folder.mkdir(parents=True)
        self.vault = build_weak_vault(self.folder / "vault.kdbx")
        self.backups = self.folder / "backups"
        self.session = VaultSession.open(self.vault, WEAK_PASSWORD, self.backups)
        self.fake = FakeDrive()
        self.token: Any = None  # what the real client would have been handed
        self.client_secret = self.data / "client_secret.json"
        self.client_secret.write_text(json.dumps(CLIENT_CONFIG), encoding="utf-8")

    def use_default_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Let a view build its own controller against the fake Drive."""
        monkeypatch.setattr(services, "HttpDriveClient", lambda token: self.fake)

    def link_account(self) -> None:
        """The token a finished sign-in would have stored, without a browser."""
        services.save_google_account(
            self.session, GoogleAccount(refresh_token=SecretStr("refresh-token-1"), email=EMAIL)
        )

    def controller(self, **kwargs: Any) -> SyncController:
        return SyncController(self.session, client_factory=self._client, **kwargs)

    def _client(self, token: Any) -> FakeDrive:
        self.token = token
        return self.fake

    def bar(self, qtbot: QtBot, **kwargs: Any) -> SyncStatusBar:
        bar = SyncStatusBar(self.controller(**kwargs))
        qtbot.addWidget(bar)
        return bar


@pytest.fixture
def profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("PV_DATA_DIR", str(tmp_path / "data"))
    made = _Profile(tmp_path)
    yield made
    made.session.close()


def _edit(profile: Any) -> None:
    """A change in the vault, saved the way the view saves it."""
    profile.session.add(make_login(title="Email", username=EMAIL, password=SecretStr(MARKER)))
    save_vault(profile.session)


# --- the status line -------------------------------------------------------


def test_an_unlinked_profile_shows_sync_off_and_a_link_button(profile: Any, qtbot: QtBot) -> None:
    bar = profile.bar(qtbot)
    assert bar.title == "Sync off"
    assert bar.link_button.isVisibleTo(bar)
    assert not bar.sync_button.isVisibleTo(bar)  # nothing to sync with
    assert not bar.controller.running


def test_the_status_line_says_synced_after_a_run(profile: Any, qtbot: QtBot) -> None:
    profile.link_account()
    bar = profile.bar(qtbot)

    bar.controller.start()
    qtbot.waitUntil(lambda: bar.title == "Synced", timeout=10_000)

    assert EMAIL in bar.detail  # whose Drive it is
    assert profile.fake.find_vault_file(PROFILE_ID) is not None


def test_the_status_line_says_waiting_to_upload_before_the_first_run(
    profile: Any, qtbot: QtBot
) -> None:
    profile.link_account()  # linked, but nothing has run yet
    bar = profile.bar(qtbot)
    assert bar.title == "Waiting to upload"


def test_the_status_line_says_waiting_when_a_change_is_not_uploaded_yet(
    profile: Any, qtbot: QtBot
) -> None:
    profile.link_account()
    bar = profile.bar(qtbot)
    bar.controller.start()
    qtbot.waitUntil(lambda: bar.title == "Synced", timeout=10_000)

    _edit(profile)
    bar.controller.engine.mark_saved()  # the save the worker is waiting out
    bar.refresh()

    assert bar.title == "Waiting to upload"


def test_the_status_line_says_offline_with_the_retry_time(profile: Any, qtbot: QtBot) -> None:
    profile.link_account()
    bar = profile.bar(qtbot)
    bar.controller.start()
    qtbot.waitUntil(lambda: bar.title == "Synced", timeout=10_000)

    profile.fake.failures = [ServerError("500")]
    bar.controller.sync_now()
    qtbot.waitUntil(lambda: bar.title == "Offline", timeout=10_000)

    assert "retrying at" in bar.detail


def test_the_status_line_says_reconnect_google_when_the_token_is_dead(
    profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "google_access_token", lambda session: "an-access-token")
    profile.link_account()
    bar = profile.bar(qtbot)
    bar.controller.start()
    qtbot.waitUntil(lambda: bar.title == "Synced", timeout=10_000)

    profile.fake.failures = [AuthExpired("401"), AuthExpired("401")]
    bar.controller.sync_now()
    qtbot.waitUntil(lambda: bar.title == "Reconnect Google", timeout=10_000)


def test_a_locked_vault_shows_sync_off_and_asks_for_no_token(profile: Any, qtbot: QtBot) -> None:
    """Locking mid-poll is not an error: it is simply not connected any more."""
    profile.link_account()
    bar = profile.bar(qtbot)
    profile.session.close()

    bar.refresh()  # the window is going away; the timer may still tick once

    assert bar.title == "Sync off"


def test_a_locked_vault_is_a_sync_error_not_a_crash(profile: Any) -> None:
    """The engine's token callable may only ever raise SyncError."""
    profile.link_account()
    profile.controller()
    profile.session.close()

    with pytest.raises(NotLinked):
        profile.token()


# --- linking and unlinking -------------------------------------------------


def test_linking_asks_for_the_file_signs_in_and_starts_syncing(
    profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile.client_secret.unlink()  # first run: the owner has not chosen a file yet
    chosen = profile.data / "downloaded-client.json"
    chosen.write_text(json.dumps(CLIENT_CONFIG), encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(chosen), ""))
    )
    signed_in: list[str] = []

    def fake_connect(session: Any) -> GoogleAccount:
        signed_in.append("connect")
        account = GoogleAccount(refresh_token=SecretStr("refresh-token-1"), email=EMAIL)
        services.save_google_account(session, account)
        return account

    monkeypatch.setattr(services, "connect_google", fake_connect)
    bar = profile.bar(qtbot)

    bar.link_button.click()
    qtbot.waitUntil(lambda: bar.title == "Synced", timeout=10_000)

    assert signed_in == ["connect"]  # oauth.connect ran, once
    assert services.google_client_secret_path().exists()  # and the file was taken in
    assert services.google_account(profile.session) is not None  # the token lives in the vault
    assert bar.controller.running  # sync started
    assert profile.fake.find_vault_file(PROFILE_ID) is not None  # and it uploaded


def test_linking_can_be_cancelled(
    profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile.client_secret.unlink()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    called: list[str] = []
    monkeypatch.setattr(services, "connect_google", lambda session: called.append("connect"))
    bar = profile.bar(qtbot)

    bar.link_button.click()

    assert called == []
    assert not bar.controller.running


def test_a_failed_link_is_reported_and_leaves_sync_off(
    profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(session: Any) -> Any:
        raise NotLinked("this profile is not connected to Google Drive")

    monkeypatch.setattr(services, "connect_google", refuse)
    bar = profile.bar(qtbot)

    bar.link_button.click()
    qtbot.waitUntil(lambda: "Could not connect" in bar.detail, timeout=10_000)

    assert bar.title == "Sync off"
    assert not bar.controller.running
    assert bar.link_button.isEnabled()


def test_unlinking_forgets_the_account_and_leaves_the_vault_alone(
    profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    _edit(profile)
    profile.link_account()
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    bar = profile.bar(qtbot)
    bar.controller.start()

    bar.unlink_button.click()

    assert google_account(profile.session) is None  # the token is gone
    assert not bar.controller.running  # and so is the worker
    assert bar.title == "Sync off"
    assert [summary.title for summary in list_logins(profile.session)] == ["Email"]
    assert profile.vault.read_bytes()  # the vault itself is where it was


def test_unlinking_asks_first(profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    profile.link_account()
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    bar = profile.bar(qtbot)

    bar.unlink_button.click()

    assert google_account(profile.session) is not None  # still connected
    assert google_account(profile.session).email == EMAIL


# --- conflicts through the banner ------------------------------------------


def _their_copy(profile: Any, title: str = "From Laptop") -> Path:
    """What another device's vault looks like: this vault, one entry further on.

    It is made from the linked vault, so it carries the Drive token the way a
    real second device's copy does.
    """
    theirs = profile.folder / "theirs.kdbx"
    shutil.copyfile(profile.vault, theirs)
    session = VaultSession.open(theirs, WEAK_PASSWORD, profile.backups)
    try:
        session.add(make_login(title=title, username="laptop@example.com"))
        session.save()
    finally:
        session.close()
    return theirs


def _a_conflict(profile: Any, controller: SyncController) -> None:
    """An edit here racing a write from another device: the upload race, exactly."""
    theirs = _their_copy(profile)
    _edit(profile)
    profile.fake.before["upload"] = lambda fake: fake.write_from_another_device(
        theirs.read_bytes(), profile_id=PROFILE_ID
    )
    controller.sync_now()


def test_a_conflict_shows_in_the_status_line_and_the_banner(
    profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile.use_default_client(monkeypatch)
    profile.link_account()
    view = VaultView(profile.session)
    qtbot.addWidget(view)
    assert view.sync is not None

    bar = view.sync
    bar.controller.start()
    qtbot.waitUntil(lambda: bar.title == "Synced", timeout=10_000)
    _a_conflict(profile, bar.controller)

    qtbot.waitUntil(lambda: not view.banner.isHidden(), timeout=10_000)

    assert bar.title == "Conflict"
    assert "action needed" in bar.detail
    assert view.banner.keep_button.isEnabled()


def test_keep_mine_ends_the_conflict_through_the_banner(
    profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile.use_default_client(monkeypatch)
    profile.link_account()
    view = VaultView(profile.session)
    qtbot.addWidget(view)
    assert view.sync is not None
    bar = view.sync
    bar.controller.start()
    qtbot.waitUntil(lambda: bar.title == "Synced", timeout=10_000)
    _a_conflict(profile, bar.controller)
    qtbot.waitUntil(lambda: not view.banner.isHidden(), timeout=10_000)

    view.banner.keep_button.click()

    assert view.banner.isHidden()
    assert bar.title == "Synced"
    kept = sorted((profile.folder / "sync" / "conflicts").glob("*.kdbx"))
    assert kept, "Drive's copy stays in conflicts/"


def test_take_theirs_reopens_the_vault_in_the_view(
    profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile.use_default_client(monkeypatch)
    profile.link_account()
    view = VaultView(profile.session)
    qtbot.addWidget(view)
    assert view.sync is not None
    bar = view.sync
    bar.controller.start()
    qtbot.waitUntil(lambda: bar.title == "Synced", timeout=10_000)
    _a_conflict(profile, bar.controller)
    qtbot.waitUntil(lambda: not view.banner.isHidden(), timeout=10_000)
    reopened: list[Any] = []
    view.restored.connect(reopened.append)

    view.banner.take_button.click()

    assert reopened, "the window must be told to reopen the vault"
    assert view.banner.isHidden()
    assert [s.title for s in list_logins(reopened[0])] == ["From Laptop"]  # theirs, not ours
    assert google_account(reopened[0]) is not None  # the link came with it
    qtbot.waitUntil(lambda: bar.title == "Synced", timeout=10_000)  # theirs goes to Drive
    file_id = profile.fake.find_vault_file(PROFILE_ID)
    assert file_id is not None
    assert profile.fake.stored_bytes(file_id.id) == profile.vault.read_bytes()


def test_a_first_link_to_a_drive_that_has_a_copy_asks_which_one_to_keep(
    profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second device, and Drive already holds this profile's vault (ADR-010)."""
    theirs = _their_copy(profile, title="From Laptop")
    profile.use_default_client(monkeypatch)
    profile.link_account()
    profile.fake.write_from_another_device(theirs.read_bytes(), profile_id=PROFILE_ID)
    view = VaultView(profile.session)  # the view's own first run meets their copy
    qtbot.addWidget(view)
    assert view.sync is not None
    bar = view.sync
    qtbot.waitUntil(lambda: bar.title == "Needs attention", timeout=10_000)

    assert "already on Google Drive" in bar.detail
    assert not bar.drive_button.isHidden()  # the question is answerable
    assert not bar.vault_button.isHidden()
    assert "upload" not in profile.fake.calls  # and nothing was decided for us

    reopened: list[Any] = []
    view.restored.connect(reopened.append)
    bar.drive_button.click()

    assert [s.title for s in list_logins(reopened[0])] == ["From Laptop"]  # theirs won
    assert [s.title for s in list_logins(bar.controller.session())] == ["From Laptop"]
    qtbot.waitUntil(lambda: bar.drive_button.isHidden(), timeout=10_000)  # question answered
    assert bar.title == "Synced"


def test_the_first_link_can_keep_this_vault_instead(
    profile: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    theirs = _their_copy(profile, title="From Laptop")
    profile.use_default_client(monkeypatch)
    profile.link_account()
    bar = profile.bar(qtbot)
    profile.fake.write_from_another_device(theirs.read_bytes(), profile_id=PROFILE_ID)
    bar.controller.start()
    qtbot.waitUntil(lambda: bar.title == "Needs attention", timeout=10_000)
    ours = profile.vault.read_bytes()

    bar.vault_button.click()

    file_id = profile.fake.find_vault_file(PROFILE_ID)
    assert file_id is not None
    assert profile.fake.stored_bytes(file_id.id) == ours  # ours won
    qtbot.waitUntil(lambda: bar.title == "Synced", timeout=10_000)


def test_an_outcome_is_ok_only_when_the_action_worked() -> None:
    assert outcome_of(SyncResult(Status.SYNCED, "Synced")).ok
    assert not outcome_of(SyncResult(Status.OFFLINE, "Drive is unreachable")).ok


# --- open both -------------------------------------------------------------


def test_open_both_shows_the_kept_copy_read_only(profile: Any, qtbot: QtBot) -> None:
    theirs = build_weak_vault(profile.folder / "kept.kdbx")
    session = VaultSession.open(theirs, WEAK_PASSWORD, profile.backups)
    session.add(
        make_login(title="Other Site", username="other@example.com", password=SecretStr(MARKER))
    )
    session.save()
    session.close()

    dialog = ConflictCopyDialog(profile.session, theirs, clear_seconds=30)
    qtbot.addWidget(dialog)
    assert dialog._list.count() == 1

    dialog._list.setCurrentRow(0)

    assert dialog._title.text() == "Other Site"
    assert dialog._password.isReadOnly()
    assert dialog._password.echoMode() == QLineEdit.EchoMode.Password
    dialog.copy_button.click()
    assert QApplication.clipboard().text() == MARKER

    dialog.close()
    with pytest.raises(VaultError):
        list_logins(dialog._copy)  # the copy is closed with the window


# --- the interval setting, and views that are not a profile -----------------


def test_the_sync_interval_is_editable_and_lands_in_settings_json(
    profile: Any, qtbot: QtBot
) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog._sync_interval.setValue(15)
    dialog._upload_quiet.setValue(3)

    dialog._save()

    assert sync_interval_minutes() == 15
    assert upload_quiet_seconds() == 3
    raw = json.loads((profile.data / "settings.json").read_text(encoding="utf-8"))
    assert raw["sync_interval_minutes"] == 15
    assert raw["upload_quiet_seconds"] == 3
    controller = profile.controller()
    assert controller.worker._interval == 15 * 60.0  # the worker waits what settings says
    assert controller.worker._save_delay == 3.0


def test_a_vault_that_is_not_a_profile_has_no_sync_line(tmp_path: Path, qtbot: QtBot) -> None:
    vault = build_weak_vault(tmp_path / "loose.kdbx")
    session = VaultSession.open(vault, WEAK_PASSWORD, tmp_path / "backups")
    view = VaultView(session)
    qtbot.addWidget(view)

    assert view.sync is None
    session.close()
