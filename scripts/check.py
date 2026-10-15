"""Run every lint, type and test check, locally and in CI.

Usage: uv run python scripts/check.py

Stops at the first failing check; each check prints its own output.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "src"


def keepassxc_cli() -> str | None:
    """Locate keepassxc-cli so the compatibility test runs when it can."""
    explicit = os.environ.get("KEEPASSXC_CLI")
    if explicit:
        return explicit
    found = shutil.which("keepassxc-cli")
    if found:
        return found
    windows_default = Path("C:/Program Files/KeePassXC/keepassxc-cli.exe")
    if windows_default.exists():
        return str(windows_default)
    return None


def run(name: str, args: list[str]) -> None:
    print(f"\n=== {name} ===", flush=True)
    env = dict(os.environ, PYTHONPATH=str(SRC))
    result = subprocess.run(args, cwd=ROOT, env=env, check=False)
    if result.returncode != 0:
        print(f"\n{name} FAILED (exit {result.returncode})", file=sys.stderr)
        raise SystemExit(result.returncode)


def main() -> None:
    cli = keepassxc_cli()
    if cli:
        os.environ["KEEPASSXC_CLI"] = cli
    run("ruff check", ["ruff", "check", "."])
    run("ruff format", ["ruff", "format", "--check", "."])
    run("mypy", ["mypy"])
    run("import-linter", ["lint-imports"])
    run("bandit", ["bandit", "-q", "-c", "pyproject.toml", "-r", "app/src"])
    run("pytest", ["pytest", "-m", "not e2e and not slow", "-q"])


if __name__ == "__main__":
    main()
