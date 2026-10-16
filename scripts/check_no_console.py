"""Fail if the extension's own code can write to a console (rule 3, invariant I2).

The extension now holds a decrypted vault in extension-only mode, so a stray
console call could print an entry field, a key or a token into a log that the
browser keeps. Vendored libraries (extension/vendor/) are pinned and reviewed
separately and are not scanned.

Usage: python scripts/check_no_console.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTENSION = ROOT / "extension"
FORBIDDEN = re.compile(r"\bconsole\s*\.|\bdebugger\b")


def main() -> int:
    problems = []
    for path in sorted(EXTENSION.rglob("*.js")):
        if "vendor" in path.relative_to(EXTENSION).parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("//", 1)[0]
            if FORBIDDEN.search(code):
                problems.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    if problems:
        print("console or debugger in extension code:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("no console or debugger calls in extension code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
