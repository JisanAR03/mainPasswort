"""Wipe the DEV data folder only (the folder PV_DATA_DIR points at).

Refuses to run unless PV_DATA_DIR is set, and never deletes the current directory.
Real vaults live elsewhere (the per-user app data folder), which this script never touches.
"""

import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    data = os.environ.get("PV_DATA_DIR")
    if not data:
        print("PV_DATA_DIR is not set; refusing to delete anything.", file=sys.stderr)
        return 1
    p = Path(data).resolve()
    if p == Path.cwd().resolve():
        print("Refusing to delete the current directory.", file=sys.stderr)
        return 1
    if not p.exists():
        print(f"{p} does not exist; nothing to do.")
        return 0
    shutil.rmtree(p)
    print(f"Deleted {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
