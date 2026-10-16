"""Install the native messaging host for Chrome and Brave ([S]).

Writes the host launcher and manifest under ``extension/native-host/``
(git-ignored) and registers the manifest path where the browsers look:

- Windows: ``HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.personalvault.host``
  and the same under ``BraveSoftware\\Brave-Browser``
- Linux: ``~/.config/google-chrome/NativeMessagingHosts/com.personalvault.host.json``
  and ``~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts/``

Run with ``uv run python scripts/install_native_host.py``, or, on a machine that
runs the PyInstaller build (M6-04) rather than a checkout, with
``--host-exe <path to personal-vault-host.exe>``.
"""

from __future__ import annotations

import argparse
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

_REPO_COMMAND = f'uv run --project "{ROOT}" python -m personal_vault.host.pm_host'


def host_command(host_exe: Path | None) -> str:
    """The command the browser runs: a packaged host executable, or this checkout.

    ``--host-exe`` is for a machine running the PyInstaller build (M6-04) — the
    browser cannot start `uv run` there, so it starts the packaged console
    program directly. Its path is used as given (absolute), because the browser
    resolves the launcher's command from a working directory of its own.
    """
    if host_exe is None:
        return _REPO_COMMAND
    return f'"{host_exe.resolve()}"'


def launcher_text(command: str) -> str:
    if os.name == "nt":
        return f"@echo off\r\n{command}\r\n"
    return f'#!/bin/sh\nexec {command} "$@"\n'


def manifest_text(launcher_path: Path) -> str:
    manifest = {
        "name": HOST_NAME,
        "description": "Personal Vault browser bridge",
        "path": str(launcher_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
    }
    return json.dumps(manifest, indent=2) + "\n"


def _write_host_files(host_exe: Path | None) -> Path:
    """Write the launcher and the manifest; returns the manifest path."""
    HOST_DIR.mkdir(parents=True, exist_ok=True)
    launcher = HOST_DIR / ("launcher.bat" if os.name == "nt" else "launcher.sh")
    launcher.write_text(launcher_text(host_command(host_exe)), encoding="utf-8")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Install the {HOST_NAME} native host")
    parser.add_argument(
        "--host-exe",
        type=Path,
        default=None,
        help="path to the packaged personal-vault-host executable (M6-04 build); "
        "default is to run the host out of this checkout with uv",
    )
    args = parser.parse_args(argv)

    if args.host_exe is not None and not args.host_exe.is_file():
        print(f"no such file: {args.host_exe}")
        return 1

    if os.name == "nt":
        manifest_path = _write_host_files(args.host_exe)
        _register_windows(manifest_path)
    elif sys.platform.startswith("linux"):
        manifest_path = _write_host_files(args.host_exe)
        _register_posix(manifest_path)
    else:
        print("unsupported platform: only Windows and Linux are supported (Q5)")
        return 1
    print(f"installed {HOST_NAME} for Chrome and Brave")
    print(f"host command: {host_command(args.host_exe)}")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
