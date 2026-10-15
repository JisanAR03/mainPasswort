"""Shared test setup: point the app at a throwaway data folder, never a real vault."""

import os
import sys
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_ROOT))  # make app/tests/fixtures importable by tests

pytest_plugins = ["fixtures.weak_vault"]


@pytest.fixture(scope="session", autouse=True)
def throwaway_data_dir(tmp_path_factory: pytest.TempPathFactory) -> None:
    data_dir = tmp_path_factory.mktemp("pv-data")
    os.environ["PV_DATA_DIR"] = str(data_dir)
