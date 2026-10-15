"""M1-01: domain model behavior ([S] review note: SecretStr redaction)."""

from __future__ import annotations

import uuid
from datetime import UTC

import pytest
from personal_vault.core.models import LoginEntry, LoginSummary, SecretStr


def test_secret_str_hides_value_in_str_and_repr() -> None:
    secret = SecretStr("hunter2")
    assert str(secret) == "***"
    assert repr(secret) == "SecretStr(***)"
    assert secret.reveal() == "hunter2"


def test_secret_str_formats_redact() -> None:
    secret = SecretStr("hunter2")
    assert f"{secret}" == "***"
    assert f"{secret:>10}" == "       ***"


def test_secret_str_equality_hash_bool_len() -> None:
    assert SecretStr("x") == SecretStr("x")
    assert hash(SecretStr("x")) == hash(SecretStr("x"))
    assert SecretStr("x") != SecretStr("y")
    assert SecretStr("x") != "x"  # never equal to a plain string
    assert bool(SecretStr("x"))
    assert not SecretStr("")
    assert len(SecretStr("abcd")) == 4


def test_login_summary_is_frozen_and_secret_free() -> None:
    summary = LoginSummary(id=uuid.uuid4(), title="GitHub", username="gh", hosts=("github.com",))
    assert summary.hosts == ("github.com",)
    with pytest.raises(AttributeError):
        summary.title = "changed"  # type: ignore[misc]


def test_login_entry_round_trip() -> None:
    from datetime import datetime

    now = datetime.now(UTC)
    entry = LoginEntry(
        id=uuid.uuid4(),
        title="GitHub",
        username="gh@example.com",
        password=SecretStr("pw"),
        urls=["https://github.com"],
        notes="",
        tags=["work"],
        match_subdomains=True,
        created_at=now,
        updated_at=now,
    )
    assert entry.title == "GitHub"
    assert entry.match_subdomains is True
    assert entry.password.reveal() == "pw"
