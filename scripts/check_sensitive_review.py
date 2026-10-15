"""CI check for ADR-009: every pull request that changes an [S] file must carry a
Security-Reviewed-By trailer in the PR body or in one of its commit messages.

Run by the sensitive-review job only; it reads BASE_SHA, HEAD_SHA and PR_BODY from the
environment.
"""

import os
import subprocess
import sys

SENSITIVE_FILES = {
    "app/src/personal_vault/core/models.py",
    "app/src/personal_vault/core/vault.py",
    "app/src/personal_vault/core/storage.py",
    "app/src/personal_vault/core/kdf.py",
    "app/src/personal_vault/core/matching.py",
    "app/src/personal_vault/core/generator.py",
    "app/src/personal_vault/core/redaction.py",
    "app/src/personal_vault/ui/clipboard.py",
    "app/src/personal_vault/ui/idle.py",
    "app/src/personal_vault/sync/decide.py",
    "app/src/personal_vault/sync/oauth.py",
    "app/src/personal_vault/bridge/server.py",
    "app/src/personal_vault/bridge/protocol.py",
    "app/src/personal_vault/bridge/pairing.py",
    "app/src/personal_vault/host/pm_host.py",
    "extension/fill.js",
    "extension/detect.js",
    "extension/background.js",
}

TRAILER = "Security-Reviewed-By:"


def _has_trailer(text: str) -> bool:
    """True when a line of ``text`` starts with the trailer (not just contains it:
    a sentence mentioning the trailer must not count as the review itself)."""
    return any(line.strip().startswith(TRAILER) for line in text.splitlines())


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return result.stdout


def main() -> int:
    base = os.environ["BASE_SHA"]
    head = os.environ["HEAD_SHA"]
    body = os.environ.get("PR_BODY", "")

    changed = set(git("diff", "--name-only", f"{base}...{head}").splitlines())
    sensitive = sorted(f for f in changed if f in SENSITIVE_FILES)
    if not sensitive:
        print("No [S] files changed; nothing to review.")
        return 0

    if _has_trailer(body) or _has_trailer(git("log", "--format=%B", f"{base}..{head}")):
        print(f"Trailer found. Reviewed files: {', '.join(sensitive)}")
        return 0

    print(
        "These security-sensitive files changed without a Security-Reviewed-By trailer:",
        file=sys.stderr,
    )
    for f in sensitive:
        print(f"  {f}", file=sys.stderr)
    print(
        "Read the diff and add 'Security-Reviewed-By: <your name>' to the PR body, "
        "then paste it into the squash commit message at merge time (ADR-009).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
