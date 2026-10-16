"""M5-05: the conflict banner and its three resolutions (pytest-qt)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core.vault import VaultSession
from personal_vault.sync.engine import Status, SyncEngine
from personal_vault.sync.fake_drive import FakeDrive
from personal_vault.ui.sync_banner import ConflictActions, SyncBanner, SyncOutcome
from personal_vault.ui.vault_view import VaultView
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.ui

CONFLICT: dict[str, object] = {
    "detected_at": "2026-10-16T09:41:07+00:00",
    "remote_version": 7,
    "remote_md5": "a" * 32,
    "kept_path": "C:/data/profiles/p1/sync/conflicts/vault-20261016T094107Z.kdbx",
}


@dataclass
class _Actions:
    """Stands in for the sync layer: records the call, answers with an outcome."""

    keep: SyncOutcome = SyncOutcome(ok=True, message="Synced")
    take: SyncOutcome = SyncOutcome(ok=True, message="Synced from Google Drive", adopted=True)
    open_error: Exception | None = None
    opened: list[Path] | None = None
    calls: list[str] | None = None

    def __post_init__(self) -> None:
        self.opened = []
        self.calls = []

    def build(self) -> ConflictActions:
        def keep_mine() -> SyncOutcome:
            assert self.calls is not None
            self.calls.append("keep_mine")
            return self.keep

        def take_theirs() -> SyncOutcome:
            assert self.calls is not None
            self.calls.append("take_theirs")
            return self.take

        def open_theirs(path: Path) -> None:
            assert self.calls is not None
            self.calls.append("open_theirs")
            if self.open_error is not None:
                raise self.open_error
            assert self.opened is not None
            self.opened.append(path)

        return ConflictActions(
            keep_mine=keep_mine, take_theirs=take_theirs, open_theirs=open_theirs
        )


@pytest.fixture
def session(tmp_path: Path) -> VaultSession:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    return VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups")


def _banner(
    qtbot: QtBot, conflict: dict[str, object] | None = CONFLICT
) -> tuple[SyncBanner, _Actions]:
    actions = _Actions()
    banner = SyncBanner()
    qtbot.addWidget(banner)
    if conflict is not None:
        banner.show_conflict(conflict, actions.build())
    return banner, actions


def test_the_banner_is_not_there_without_a_conflict(qtbot: QtBot) -> None:
    banner, _ = _banner(qtbot, None)
    assert banner.isHidden()


def test_a_conflict_shows_the_time_the_kept_copy_and_three_choices(qtbot: QtBot) -> None:
    banner, _ = _banner(qtbot)
    assert not banner.isHidden()
    assert "both copies changed" in banner.heading.lower()
    assert "2026-10-16 09:41 UTC" in banner.detail
    assert "vault-20261016T094107Z.kdbx" in banner.detail
    assert banner.keep_button.text() == "Keep mine"
    assert banner.take_button.text() == "Take theirs"
    assert banner.open_button.text() == "Open both"


def test_keep_mine_uploads_then_takes_the_banner_away(qtbot: QtBot) -> None:
    banner, actions = _banner(qtbot)
    resolved: list[object] = []
    banner.resolved.connect(resolved.append)

    banner.keep_button.click()

    assert actions.calls == ["keep_mine"]
    assert banner.isHidden()
    assert resolved == [actions.keep]


def test_take_theirs_adopts_and_reports_that_the_vault_changed(qtbot: QtBot) -> None:
    banner, actions = _banner(qtbot)
    resolved: list[object] = []
    banner.resolved.connect(resolved.append)

    banner.take_button.click()

    assert actions.calls == ["take_theirs"]
    assert banner.isHidden()
    assert resolved == [actions.take]
    assert resolved[0].adopted is True


def test_a_failed_resolution_keeps_the_banner_and_says_why(qtbot: QtBot) -> None:
    actions = _Actions(keep=SyncOutcome(ok=False, message="Google Drive is not reachable"))
    banner = SyncBanner()
    qtbot.addWidget(banner)
    banner.show_conflict(CONFLICT, actions.build())

    banner.keep_button.click()

    assert not banner.isHidden()  # the conflict is still standing
    assert "not reachable" in banner.status
    assert banner.keep_button.isEnabled()  # and the owner can try again


def test_open_both_shows_the_kept_copy_and_leaves_the_conflict(qtbot: QtBot) -> None:
    banner, actions = _banner(qtbot)

    banner.open_button.click()

    assert actions.calls == ["open_theirs"]
    assert actions.opened == [Path(str(CONFLICT["kept_path"]))]
    assert not banner.isHidden()  # looking at both resolves nothing by itself


def test_open_both_reports_a_copy_that_will_not_open(qtbot: QtBot) -> None:
    actions = _Actions(open_error=ValueError("that copy does not open with this master password"))
    banner = SyncBanner()
    qtbot.addWidget(banner)
    banner.show_conflict(CONFLICT, actions.build())

    banner.open_button.click()

    assert not banner.isHidden()
    assert "does not open" in banner.status


# --- and where it hangs in the vault view ---------------------------------


def test_the_vault_view_hides_the_banner_until_a_conflict_arrives(
    qtbot: QtBot, session: VaultSession
) -> None:
    view = VaultView(session)
    qtbot.addWidget(view)
    assert view.banner.isHidden()

    actions = _Actions()
    view.set_conflict(CONFLICT, actions.build())

    assert not view.banner.isHidden()
    view.set_conflict(None, actions.build())
    assert view.banner.isHidden()


def test_the_vault_view_reloads_its_list_when_a_resolution_changed_the_vault(
    qtbot: QtBot, session: VaultSession
) -> None:
    view = VaultView(session)
    qtbot.addWidget(view)
    actions = _Actions()
    view.set_conflict(CONFLICT, actions.build())
    reported: list[object] = []
    view.sync_resolved.connect(reported.append)

    view.banner.take_button.click()

    assert reported == [actions.take]
    assert view.banner.isHidden()


# --- and with the real engine behind the three buttons ---------------------

PROFILE = "9f2c1d3e4b5a69788796a5b4c3d2e1f0"


class _Conflict:
    """A real profile, mid-conflict: the other laptop wrote last, we edited too."""

    def __init__(self, tmp_path: Path) -> None:
        self.vault = build_weak_vault(tmp_path / "vault.kdbx")
        self.fake = FakeDrive()
        self.engine = SyncEngine(
            client=self.fake,
            vault_path=self.vault,
            backups_dir=tmp_path / "backups",
            sync_dir=tmp_path / "sync",
            profile_id=PROFILE,
            verify_decrypts=_decrypts,
            refresh_credentials=lambda: None,
        )
        assert self.engine.run_once().status is Status.SYNCED  # linked
        with VaultSession.open(self.vault, WEAK_PASSWORD, tmp_path / "backups") as session:
            session.add(make_login(title="Mine"))
            session.save()
        self.engine.mark_saved()
        theirs = build_weak_vault(tmp_path / "theirs.kdbx")
        self.fake.before["upload"] = lambda drive: drive.write_from_another_device(
            theirs.read_bytes(), profile_id=PROFILE
        )
        assert self.engine.run_once().status is Status.CONFLICT
        self.conflict = self.engine.state().conflict
        assert self.conflict is not None

    def actions(self) -> ConflictActions:
        return ConflictActions(
            keep_mine=lambda: _describe(self.engine.upload_local()),
            take_theirs=lambda: _describe(self.engine.adopt_remote()),
            open_theirs=lambda path: path.read_bytes(),  # read-only: never written back
        )

    def kept(self) -> list[Path]:
        return sorted((self.engine.sync_dir / "conflicts").glob("*.kdbx"))


def _decrypts(path: Path) -> bool:
    try:
        VaultSession.open(path, WEAK_PASSWORD, path.parent)
    except Exception:
        return False
    return True


def _describe(result: object) -> SyncOutcome:
    """What M5-06's services.py will do with a SyncResult for the banner."""
    return SyncOutcome(
        ok=result.status is Status.SYNCED,  # type: ignore[attr-defined]
        message=result.message,  # type: ignore[attr-defined]
        adopted=result.adopted,  # type: ignore[attr-defined]
    )


def test_keep_mine_with_the_real_engine_uploads_and_keeps_their_copy(
    qtbot: QtBot, tmp_path: Path
) -> None:
    case = _Conflict(tmp_path)
    before = [p.name for p in case.kept()]
    banner = SyncBanner()
    qtbot.addWidget(banner)
    banner.show_conflict(case.conflict, case.actions())
    ours = case.vault.read_bytes()

    banner.keep_button.click()

    assert banner.isHidden()
    file_id = case.fake.find_vault_file(PROFILE)
    assert file_id is not None
    assert case.fake.stored_bytes(file_id.id) == ours  # ours went up
    assert [p.name for p in case.kept()] == before  # theirs is still in conflicts/


def test_take_theirs_with_the_real_engine_backs_up_then_adopts(
    qtbot: QtBot, tmp_path: Path
) -> None:
    case = _Conflict(tmp_path)
    ours = case.vault.read_bytes()
    banner = SyncBanner()
    qtbot.addWidget(banner)
    banner.show_conflict(case.conflict, case.actions())

    banner.take_button.click()

    assert banner.isHidden()
    assert case.vault.read_bytes() != ours  # theirs is the vault now
    backups = sorted((tmp_path / "backups").glob("vault-*.kdbx"))
    assert any(backup.read_bytes() == ours for backup in backups)  # ours was backed up first
