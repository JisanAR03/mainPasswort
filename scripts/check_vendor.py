"""Fail if a vendored extension file differs from the hash pinned in VENDOR.md.

The extension carries third-party code (extension/vendor/, see VENDOR.md) that is
copied byte for byte from npm tarballs. This check makes any change to those bytes —
an accidental edit or a swapped file — fail CI until VENDOR.md is updated and reviewed.

Usage: python scripts/check_vendor.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "extension" / "vendor"
PIN = re.compile(r"^([0-9a-f]{64})  (\S+)$")


def pinned() -> dict[str, str]:
    text = (VENDOR / "VENDOR.md").read_text(encoding="utf-8")
    pins = {}
    for line in text.splitlines():
        match = PIN.match(line.strip())
        if match:
            pins[match.group(2)] = match.group(1)
    return pins


def main() -> int:
    pins = pinned()
    if not pins:
        print("VENDOR.md pins no files", file=sys.stderr)
        return 1
    present = {p.name for p in VENDOR.iterdir() if p.is_file() and p.name != "VENDOR.md"}
    problems = []
    for name in sorted(present - set(pins)):
        problems.append(f"{name}: in extension/vendor/ but not pinned in VENDOR.md")
    for name, expected in sorted(pins.items()):
        path = VENDOR / name
        if not path.is_file():
            problems.append(f"{name}: pinned in VENDOR.md but missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            problems.append(f"{name}: sha256 {actual} does not match the pinned {expected}")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(f"{len(pins)} vendored files match VENDOR.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
