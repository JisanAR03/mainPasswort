"""M6-01: the "Merge both" button on the conflict banner, and what it does.

The banner tests here use a stand-in for the sync layer; the last two run the
real SyncController against FakeDrive, so a merge is a real merge of two vault
files followed by a real upload.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core.models import SecretStr
from personal_vault.core.vault import VaultSession
from personal_vault.services import Status, SyncController, save_google_account, save_vault
from personal_vault.sync.fake_drive import FakeDrive
from personal_vault.sync.oauth import GoogleAccount
from personal_vault.ui.sync_banner import ConflictActions, SyncBanner, SyncOutcome
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.ui

PROFILE_ID = "p_mergeprofile"
EMAIL = "owner@example.com"
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = T0 + timedelta(hours=1)
CONFLICT: dict[str, object] = {
    "detected_at": "2026-10-16T09:41:07+00:00",
    "remote_version": 7,
    "remote_md5": "a" * 32,
    "kept_path": "C:/data/profiles/p1/sync/conflicts/vault-20261016T094107Z.kdbx",
}


@dataclass
class _Actions:
    """Stands in for the sync layer: records the call, answers with an outcome."""

    merged: SyncOutcome = SyncOutcome(ok=True, message="merged 1 changed, 0 added and 0 deleted")
    calls: list[str] | None = None

    def __post_init__(self) -> None:
        self.calls = []

    def build(self) -> ConflictActions:
        def merge_both() -> SyncOutcome:
            assert self.calls is not None
            self.calls.append("merge_both")
            return self.merged

        return ConflictActions(
            keep_mine=lambda: self.merged,
            take_theirs=lambda: self.merged,
            open_theirs=lambda path: None,
            merge_both=merge_both,
        )


def test_the_banner_offers_merge_both_beside_the_other_choices(qtbot: QtBot) -> None:
    banner = SyncBanner()
    qtbot.addWidget(banner)

    banner.show_conflict(CONFLICT, _Actions().build())

    assert banner.merge_button.text() == "Merge both"
    assert banner.merge_button.isEnabled()
    # the entries that landed in M5-05 are still there
    assert banner.keep_button.text() == "Keep mine"
    assert banner.take_button.text() == "Take theirs"


def test_merge_both_ends_the_conflict_and_reports_what_needs_reloading(qtbot: QtBot) -> None:
    actions = _Actions()
    banner = SyncBanner()
    qtbot.addWidget(banner)
    banner.show_conflict(CONFLICT, actions.build())
    resolved: list[object] = []
    banner.resolved.connect(resolved.append)

    banner.merge_button.click()

    assert actions.calls == ["merge_both"]
    assert banner.isHidden()
    assert resolved == [actions.merged]
    # a merge keeps this vault and writes to it: the file is not replaced
    assert resolved[0].adopted is False


def test_a_merge_that_could_not_upload_leaves_the_conflict_standing(qtbot: QtBot) -> None:
    actions = _Actions(merged=SyncOutcome(ok=False, message="Google Drive is not reachable"))
    banner = SyncBanner()
    qtbot.addWidget(banner)
    banner.show_conflict(CONFLICT, actions.build())

    banner.merge_button.click()

    assert not banner.isHidden()
    assert "not reachable" in banner.status
    assert banner.merge_button.isEnabled()  # the owner can try again


# --- and with the real engine and a real vault pair ------------------------


class _Pair:
    """A real profile mid-conflict: one shared entry, edited on each device.

    The other device also added an entry of its own, so a merge has something to
    take from both sides.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.folder = tmp_path / "data" / "profiles" / PROFILE_ID
        self.folder.mkdir(parents=True)
        self.vault = build_weak_vault(self.folder / "vault.kdbx")
        self.session = VaultSession.open(self.vault, WEAK_PASSWORD, self.folder / "backups")
        save_google_account(
            self.session, GoogleAccount(refresh_token=SecretStr("refresh-token"), email=EMAIL)
        )
        self.fake = FakeDrive()
        self.controller = SyncController(self.session, client_factory=lambda token: self.fake)
        assert self.controller.engine.run_once().status is Status.SYNCED  # the first link

        # an entry both devices have, on Drive
        self.shared = make_login(updated_at=T0)
        self.session.add(self.shared)
        save_vault(self.session)
        self.controller.engine.mark_saved()
        assert self.controller.engine.run_once().status is Status.SYNCED

        # the other device, holding that same file, edits it later and adds one
        self.theirs = tmp_path / "theirs.kdbx"
        shutil.copyfile(self.vault, self.theirs)
        with VaultSession.open(self.theirs, WEAK_PASSWORD, tmp_path / "their-backups") as other:
            changed = other.get(self.shared.id)
            changed.title = "Renamed there"
            changed.updated_at = LATER
            other.edit(changed)
            other.add(make_login(title="Only there"))
            other.save()

        # and we edit the same entry earlier, then try to upload it
        ours = self.session.get(self.shared.id)
        ours.title = "Renamed here"
        ours.updated_at = T0 + timedelta(minutes=30)
        self.session.edit(ours)
        save_vault(self.session)
        self.controller.engine.mark_saved()
        self.fake.before["upload"] = lambda drive: drive.write_from_another_device(
            self.theirs.read_bytes(), profile_id=PROFILE_ID
        )
        assert self.controller.engine.run_once().status is Status.CONFLICT

    def titles(self) -> list[str]:
        return sorted(summary.title for summary in self.session.list_logins())

    def kept(self) -> list[Path]:
        return sorted((self.folder / "sync" / "conflicts").glob("*.kdbx"))


def test_a_merge_keeps_both_sides_edits_and_the_entry_only_they_had(tmp_path: Path) -> None:
    pair = _Pair(tmp_path)
    assert pair.titles() == ["Renamed here"]  # nothing merged yet

    result = pair.controller.merge_both()

    assert result.status is Status.SYNCED
    assert result.message == "merged 1 changed, 1 added and 0 deleted from Drive's copy"
    assert pair.titles() == ["Only there", "Renamed there"]


def test_a_merge_ends_the_conflict_and_puts_the_merged_file_on_drive(tmp_path: Path) -> None:
    """The milestone's own line: merging ends the conflict and uploads."""
    pair = _Pair(tmp_path)

    pair.controller.merge_both()

    assert pair.controller.report().status is Status.SYNCED  # no conflict any more
    assert pair.kept()  # their bytes are still in conflicts/ for the owner
    file_id = pair.fake.find_vault_file(PROFILE_ID)
    assert file_id is not None
    assert pair.fake.stored_bytes(file_id.id) == pair.vault.read_bytes()


def test_merge_both_after_the_conflict_is_over_changes_nothing(tmp_path: Path) -> None:
    """The button is gone with the banner, but a second call must be harmless."""
    pair = _Pair(tmp_path)
    pair.controller.merge_both()
    stored = pair.fake.stored_bytes(pair.fake.find_vault_file(PROFILE_ID).id)  # type: ignore[union-attr]

    again = pair.controller.merge_both()

    assert again.status is Status.ATTENTION
    assert "not here any more" in again.message
    assert pair.titles() == ["Only there", "Renamed there"]
    assert pair.fake.stored_bytes(pair.fake.find_vault_file(PROFILE_ID).id) == stored  # type: ignore[union-attr]
