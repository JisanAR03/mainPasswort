"""M1-06: profile and settings stores with schema versioning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from personal_vault.core.errors import SchemaTooNewError
from personal_vault.core.profiles import ProfileStore
from personal_vault.core.settings import SettingsStore

pytestmark = pytest.mark.integration


def test_profile_create_list_rename_delete(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.load()
    profile = store.create("Work")
    assert profile.id.startswith("p_")
    assert profile.sync_enabled is False
    assert [p.display_name for p in store.list()] == ["Work"]
    store.rename(profile.id, "Work stuff")
    assert [p.display_name for p in store.list()] == ["Work stuff"]
    store.set_last_used(profile.id)
    assert store.last_used() == profile.id
    store.delete(profile.id)
    assert store.list() == []
    assert store.last_used() is None


def test_profiles_are_isolated_between_data_dirs(tmp_path: Path) -> None:
    first = ProfileStore(tmp_path / "a")
    second = ProfileStore(tmp_path / "b")
    first.load()
    second.load()
    first.create("Only in A")
    assert [p.display_name for p in second.list()] == []


def test_profile_name_validation(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.load()
    with pytest.raises(ValueError):
        store.create("")
    with pytest.raises(ValueError):
        store.create("x" * 101)
    with pytest.raises(KeyError):
        store.rename("missing", "Name")
    with pytest.raises(KeyError):
        store.set_last_used("missing")


def test_newer_schema_profiles_open_read_only(tmp_path: Path) -> None:
    (tmp_path / "profiles.json").write_text(
        json.dumps({"schema_version": 99, "last_used_profile_id": None, "profiles": []}),
        encoding="utf-8",
    )
    store = ProfileStore(tmp_path)
    store.load()
    assert store.list() == []
    with pytest.raises(SchemaTooNewError):
        store.create("Nope")
    with pytest.raises(SchemaTooNewError):
        store.set_last_used("p_x")
    with pytest.raises(SchemaTooNewError):
        store.delete("p_x")
    # The newer file was not overwritten.
    assert (
        json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))["schema_version"] == 99
    )


def test_settings_defaults_and_round_trip(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path)
    store.load()
    assert store.get("clipboard_clear_seconds") == 30
    assert store.get("lock_on_sleep") is True
    assert store.get("idle_lock_minutes") == 5
    assert store.get("generator") == {
        "length": 20,
        "upper": True,
        "lower": True,
        "digits": True,
        "symbols": True,
        "exclude_lookalikes": True,
    }
    store.set("clipboard_clear_seconds", 45)
    assert store.get("clipboard_clear_seconds") == 45
    store.set(
        "generator",
        {
            "length": 32,
            "upper": True,
            "lower": True,
            "digits": True,
            "symbols": False,
            "exclude_lookalikes": True,
        },
    )
    assert store.get("generator")["length"] == 32


def test_settings_validation(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path)
    store.load()
    with pytest.raises(KeyError):
        store.set("no_such_setting", 1)
    with pytest.raises(ValueError):
        store.set("clipboard_clear_seconds", 0)
    with pytest.raises(ValueError):
        store.set("clipboard_clear_seconds", "30")
    with pytest.raises(ValueError):
        store.set("lock_on_sleep", "yes")
    with pytest.raises(ValueError):
        store.set("generator", {"length": 2})


def test_newer_schema_settings_open_read_only(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text(
        json.dumps({"schema_version": 99, "clipboard_clear_seconds": 12}),
        encoding="utf-8",
    )
    store = SettingsStore(tmp_path)
    store.load()
    assert store.get("clipboard_clear_seconds") == 12
    with pytest.raises(SchemaTooNewError):
        store.set("clipboard_clear_seconds", 30)
    assert (
        json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))[
            "clipboard_clear_seconds"
        ]
        == 12
    )
