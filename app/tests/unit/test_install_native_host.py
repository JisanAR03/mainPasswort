"""M3-04: the install script writes a manifest restricted to our extension ID."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "install_native_host.py"

spec = importlib.util.spec_from_file_location("install_native_host", SCRIPT)
assert spec is not None and spec.loader is not None
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def test_manifest_restricts_allowed_origins_to_our_extension_id() -> None:
    manifest = json.loads(install.manifest_text(Path("C:/vault/launcher.bat")))
    assert manifest["name"] == "com.personalvault.host"
    assert manifest["type"] == "stdio"
    assert manifest["path"] == str(Path("C:/vault/launcher.bat"))
    assert manifest["allowed_origins"] == ["chrome-extension://pkmjgefocdecdncjcpdlohfnahebkkpi/"]


def test_launcher_runs_the_host_module() -> None:
    text = install.launcher_text()
    assert "python -m personal_vault.host.pm_host" in text


class _FakeKey:
    def __enter__(self) -> _FakeKey:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self) -> None:
        self.keys: list[tuple[str, str]] = []
        self.values: list[tuple[object, object, str]] = []

    def CreateKey(self, hive: str, subkey: str) -> _FakeKey:
        self.keys.append((hive, subkey))
        return _FakeKey()

    def SetValueEx(self, key: object, name: object, reserved: int, kind: int, value: str) -> None:
        self.values.append((name, kind, value))


def test_windows_registration_covers_chrome_and_brave(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)  # type: ignore[arg-type]
    install._register_windows(Path("C:/vault/manifest.json"))
    assert fake.keys == [
        ("HKCU", r"Software\Google\Chrome\NativeMessagingHosts\com.personalvault.host"),
        (
            "HKCU",
            r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.personalvault.host",
        ),
    ]
    assert fake.values == [(None, 1, str(Path("C:/vault/manifest.json")))] * 2


def test_posix_registration_covers_chrome_and_brave(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(install.Path, "home", staticmethod(lambda: tmp_path))
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"name": "com.personalvault.host"}', encoding="utf-8")
    install._register_posix(manifest)
    chrome_manifest = (
        tmp_path / ".config/google-chrome/NativeMessagingHosts/com.personalvault.host.json"
    )
    assert chrome_manifest.read_text(encoding="utf-8") == '{"name": "com.personalvault.host"}'
    brave_manifest = (
        tmp_path
        / ".config/BraveSoftware/Brave-Browser/NativeMessagingHosts/com.personalvault.host.json"
    )
    assert brave_manifest.exists()
