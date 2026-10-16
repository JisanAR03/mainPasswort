# PyInstaller spec for Personal Vault (M6-04). Build it with
# `uv run --group build python scripts/build_app.py`; see docs/install.md.
#
# One build, one folder, two programs:
#
#   PersonalVault.exe        the desktop app. Windowed (`console=False`), so no
#                            black console window opens behind it.
#   personal-vault-host.exe  the browser's native messaging host. Console kept
#                            (`console=True`): Chrome and Brave talk to it over
#                            stdio, and a windowed build has no stdio to give.
#
# The host is analyzed on its own and without Qt, because it imports nothing
# but the stdlib and bridge/protocol.py — it must stay a small plain console
# program. Both programs are laid into one folder by a single COLLECT, which
# is why the folder carries the Qt libraries the host will never load.
#
# onedir, never onefile: onefile unpacks the whole app, Qt and all, into a temp
# folder on every start, and a password manager should not leave copies of
# itself behind in %TEMP% or slow its own startup down doing it.
#
# PyInstaller does not cross-compile: run this on the OS you want the folder for.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
SRC = ROOT / "app" / "src"

# pykeepass ships a blank KDBX as package data and reads it every time a vault
# is created (`create_database`). No PyInstaller hook collects it, so without
# this line the built app starts, shows the profile picker, and then dies the
# moment someone creates a vault: FileNotFoundError: .../pykeepass/blank_database.kdbx
PYKEEPASS_DATA = collect_data_files("pykeepass")

ENTRY = str(SRC / "personal_vault" / "__main__.py")
HOST_ENTRY = str(SRC / "personal_vault" / "host" / "pm_host.py")

# Nothing in the tree imports these; naming them keeps them out of the folder.
# QtWebEngine and the Qt add-ons alone are several hundred megabytes.
EXCLUDES = [
    "tkinter",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtMultimedia",
    "PySide6.QtPdf",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
]

app_analysis = Analysis(
    [ENTRY],
    pathex=[str(SRC)],
    datas=PYKEEPASS_DATA,
    excludes=EXCLUDES,
    noarchive=False,
)
app_pyz = PYZ(app_analysis.pure)

app_exe = EXE(
    app_pyz,
    app_analysis.scripts,
    [],
    exclude_binaries=True,
    name="PersonalVault",
    console=False,
    upx=False,
    disable_windowed_traceback=False,
)

# The host gets its own analysis: no Qt at all in it.
host_analysis = Analysis(
    [HOST_ENTRY],
    pathex=[str(SRC)],
    excludes=EXCLUDES + ["PySide6"],
    noarchive=False,
)
host_pyz = PYZ(host_analysis.pure)

host_exe = EXE(
    host_pyz,
    host_analysis.scripts,
    [],
    exclude_binaries=True,
    name="personal-vault-host",
    console=True,
    upx=False,
)

COLLECT(
    app_exe,
    app_analysis.binaries,
    app_analysis.datas,
    host_exe,
    host_analysis.binaries,
    host_analysis.datas,
    strip=False,
    upx=False,
    name="PersonalVault",
)
