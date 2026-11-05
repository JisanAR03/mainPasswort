"""Shared test setup: make app/tests/fixtures importable and load the weak-vault fixtures."""

import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_ROOT))  # make app/tests/fixtures importable by tests

pytest_plugins = ["fixtures.weak_vault"]
