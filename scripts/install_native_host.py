"""Install the native messaging host for Chrome and Brave ([S]).

Writes the host launcher and manifest under ``extension/native-host/``
(git-ignored) and registers the manifest path where the browsers look:

- Windows: ``HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.personalvault.host``
  and the same under ``BraveSoftware\\Brave-Browser``
- Linux: ``~/.config/google-chrome/NativeMessagingHosts/com.personalvault.host.json``
  and ``~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts/``

Run with ``uv run python scripts/install_native_host.py``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_NAME = "com.personalvault.host"
HOST_DIR = ROOT / "extension" / "native-host"
# The extension ID of extension/key.pem (scripts/generate_extension_key.py).
# If the keypair is ever regenerated, update this constant with the new ID.
EXTENSION_ID = "pkmjgefocdecdncjcpdlohfnahebkkpi"

_COMMAND = f'uv run --project "{ROOT}" python -m personal_vault.host.pm_host'


def launcher_text() -> str:
    if os.name == "nt":
        return f"@echo off\r\n{_COMMAND}\r\n"
    return f'#!/bin/sh\nexec {_COMMAND} "$@"\n'


def manifest_text(launcher_path: Path) -> str:
    manifest = {
        "name": HOST_NAME,
        "description": "Personal Vault browser bridge",
        "path": str(launcher_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
    }
    return json.dumps(manifest, indent=2) + "\n"


def _write_host_files() -> Path:
    """Write the launcher and the manifest; returns the manifest path."""
    HOST_DIR.mkdir(parents=True, exist_ok=True)
    launcher = HOST_DIR / ("launcher.bat" if os.name == "nt" else "launcher.sh")
    launcher.write_text(launcher_text(), encoding="utf-8")
    if os.name != "nt":
        launcher.chmod(0o755)
    manifest_path = HOST_DIR / f"{HOST_NAME}.json"
    manifest_path.write_text(manifest_text(launcher), encoding="utf-8")
    return manifest_path


def _register_windows(manifest_path: Path) -> None:
    import winreg

    for hive in (
        r"Software\Google\Chrome\NativeMessagingHosts",
        r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    ):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{hive}\\{HOST_NAME}") as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(manifest_path))


def _register_posix(manifest_path: Path) -> None:
    text = manifest_path.read_text(encoding="utf-8")
    for config_dir in (
        Path.home() / ".config" / "google-chrome" / "NativeMessagingHosts",
        Path.home() / ".config" / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts",
    ):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / f"{HOST_NAME}.json").write_text(text, encoding="utf-8")


def main() -> int:
    if os.name == "nt":
        manifest_path = _write_host_files()
        _register_windows(manifest_path)
    elif sys.platform.startswith("linux"):
        manifest_path = _write_host_files()
        _register_posix(manifest_path)
    else:
        print("unsupported platform: only Windows and Linux are supported (Q5)")
        return 1
    print(f"installed {HOST_NAME} for Chrome and Brave")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
