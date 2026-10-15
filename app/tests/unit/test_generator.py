"""M1-07: password generator ([S])."""

from __future__ import annotations

import pytest
from personal_vault.core.generator import (
    DIGITS,
    LOOKALIKES,
    LOWER,
    SYMBOLS,
    UPPER,
    generate_password,
)
from personal_vault.core.models import SecretStr

pytestmark = pytest.mark.unit


def test_default_password_meets_spec() -> None:
    password = generate_password()
    assert isinstance(password, SecretStr)
    value = password.reveal()
    assert len(value) == 20
    assert any(c in UPPER for c in value)
    assert any(c in LOWER for c in value)
    assert any(c in DIGITS for c in value)
    assert any(c in SYMBOLS for c in value)
    assert not set(value) & LOOKALIKES


def test_custom_length_and_classes() -> None:
    value = generate_password(64, upper=True, lower=True, digits=True, symbols=False).reveal()
    assert len(value) == 64
    assert any(c in UPPER for c in value)
    assert any(c in LOWER for c in value)
    assert any(c in DIGITS for c in value)
    assert all(c not in SYMBOLS for c in value)


def test_every_enabled_class_appears_even_at_minimum_length() -> None:
    value = generate_password(4, upper=True, lower=True, digits=True, symbols=True).reveal()
    assert len(value) == 4
    assert sum(c in UPPER for c in value) == 1
    assert sum(c in LOWER for c in value) == 1
    assert sum(c in DIGITS for c in value) == 1
    assert sum(c in SYMBOLS for c in value) == 1


def test_lookalikes_allowed_when_not_excluded() -> None:
    values = [generate_password(64, exclude_lookalikes=False).reveal() for _ in range(8)]
    assert all(set(value) <= set(UPPER + LOWER + DIGITS + SYMBOLS) for value in values)
    assert any(set(value) & LOOKALIKES for value in values)


def test_randomness_comes_from_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_choice(pool: str) -> str:
        calls.append("choice")
        return pool[0]

    def fake_randbelow(n: int) -> int:
        calls.append("randbelow")
        return 0

    monkeypatch.setattr("personal_vault.core.generator.secrets.choice", fake_choice)
    monkeypatch.setattr("personal_vault.core.generator.secrets.randbelow", fake_randbelow)
    value = generate_password(8).reveal()
    assert len(value) == 8
    assert "choice" in calls and "randbelow" in calls


def test_length_bounds() -> None:
    with pytest.raises(ValueError):
        generate_password(3)
    with pytest.raises(ValueError):
        generate_password(4097)


def test_no_classes_refused() -> None:
    with pytest.raises(ValueError):
        generate_password(20, upper=False, lower=False, digits=False, symbols=False)
