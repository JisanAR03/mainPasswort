"""Pre-commit hook: fail on any staged file over 500 KB.

Receives every staged file as arguments; only files that exist in the working tree are
checked (deleted files are skipped).
"""

import sys
from pathlib import Path

MAX_KB = 500


def main() -> int:
    bad = [
        p for arg in sys.argv[1:] if (p := Path(arg)).is_file() and p.stat().st_size > MAX_KB * 1024
    ]
    if bad:
        for p in bad:
            print(
                f"{p}: {p.stat().st_size // 1024} KB exceeds the {MAX_KB} KB limit", file=sys.stderr
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
