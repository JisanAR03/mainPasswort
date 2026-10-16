"""Build the desktop app folder with PyInstaller (M6-04).

    uv run --group build python scripts/build_app.py

Writes ``dist/PersonalVault/`` holding both executables — the app and the
browser's native messaging host — and prints what it produced and how big it
is. ``build/pyinstaller/`` holds PyInstaller's scratch files; both folders are
git-ignored.

The build is per-OS: PyInstaller does not cross-compile, so the folder is for
the machine that built it. Nothing here touches a vault.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "personal-vault.spec"
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
APP_DIR = DIST / "PersonalVault"
APP_EXE = APP_DIR / ("PersonalVault.exe" if sys.platform == "win32" else "PersonalVault")
HOST_EXE = APP_DIR / (
    "personal-vault-host.exe" if sys.platform == "win32" else "personal-vault-host"
)


# Files the app reads at runtime that PyInstaller will happily leave out: it
# reports a successful build and the app dies only when that code path runs.
# pykeepass reads this one the moment a vault is created, so a build without it
# starts, shows the picker, and fails on the first profile — found exactly that
# way, with a frozen check, before this guard existed.
REQUIRED_RUNTIME_FILES = ("blank_database.kdbx",)


def folder_size(path: Path) -> str:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return f"{total / 1024 / 1024:.1f} MiB"


def missing_runtime_files(folder: Path) -> list[str]:
    present = {p.name for p in folder.rglob("*")}
    return [name for name in REQUIRED_RUNTIME_FILES if name not in present]


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run: uv sync --group build")
        return 1

    if sys.platform not in ("win32", "linux"):
        print(f"unsupported platform for a supported build: {sys.platform} (Q5)")
        return 1

    # A stale folder from an older build would be copied over the top of the
    # new one, so that an executable removed from the spec lingers in dist/.
    shutil.rmtree(APP_DIR, ignore_errors=True)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(WORK),
            str(SPEC),
        ],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        print(f"PyInstaller failed with exit code {result.returncode}")
        return result.returncode

    missing = [p for p in (APP_EXE, HOST_EXE) if not p.is_file()]
    if missing:
        print("the build finished but these are missing: " + ", ".join(map(str, missing)))
        return 1

    absent = missing_runtime_files(APP_DIR)
    if absent:
        print("the folder is missing files the app reads at runtime: " + ", ".join(absent))
        print("collect them in packaging/personal-vault.spec (collect_data_files) and build again")
        return 1

    print(f"\nbuilt {APP_DIR} ({folder_size(APP_DIR)})")
    print(f"  app:  {APP_EXE}")
    print(f"  host: {HOST_EXE}")
    print("\nnext: docs/install.md — install, update, and point the browser at the packaged host")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
