"""M0-01: the skeleton runs one passing test, locally and in CI."""

import personal_vault


def test_skeleton() -> None:
    assert personal_vault.__version__ == "0.1.0"
