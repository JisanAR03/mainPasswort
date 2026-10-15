"""Pre-commit hook: block *.kdbx outside app/tests/fixtures/ and any client_secret*.json.

Receives the staged filenames that matched the hook's `files` pattern as arguments.
"""

import sys
from pathlib import Path

ALLOWED = Path("app/tests/fixtures")
MAX_KB = 500


def main() -> int:
    bad: list[str] = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        name = p.name.lower()
        if name.endswith(".kdbx") and not p.is_relative_to(ALLOWED):
            bad.append(f"{p}: *.kdbx may only be committed under {ALLOWED}/")
        elif name.startswith("client_secret") and name.endswith(".json"):
            bad.append(f"{p}: client_secret*.json must never be committed")
    if bad:
        for line in bad:
            print(line, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
