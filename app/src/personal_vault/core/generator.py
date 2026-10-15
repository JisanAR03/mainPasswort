"""Password generator ([S]). Randomness only from the secrets module."""

from __future__ import annotations

import secrets

from personal_vault.core.models import SecretStr

UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LOWER = "abcdefghijklmnopqrstuvwxyz"
DIGITS = "0123456789"
SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?/|~"
# The look-alike set we exclude: letters and digits that read alike, plus the
# pipe in symbols. Documented choice; the spec leaves the exact set open.
LOOKALIKES = frozenset("0Oo1lI|")
MAX_LENGTH = 4096


def generate_password(
    length: int = 20,
    *,
    upper: bool = True,
    lower: bool = True,
    digits: bool = True,
    symbols: bool = True,
    exclude_lookalikes: bool = True,
) -> SecretStr:
    """Generate a password with at least one character of every enabled class."""
    if not 4 <= length <= MAX_LENGTH:
        raise ValueError(f"length must be 4-{MAX_LENGTH}")
    pools = []
    if upper:
        pools.append(UPPER)
    if lower:
        pools.append(LOWER)
    if digits:
        pools.append(DIGITS)
    if symbols:
        pools.append(SYMBOLS)
    if not pools:
        raise ValueError("at least one character class must be enabled")
    if length < len(pools):
        raise ValueError("length must be at least the number of enabled classes")
    if exclude_lookalikes:
        pools = ["".join(c for c in pool if c not in LOOKALIKES) for pool in pools]
        if any(not pool for pool in pools):
            raise ValueError("exclude_lookalikes removed every character of a class")
    combined = "".join(pools)
    chars = [secrets.choice(pool) for pool in pools]
    chars += [secrets.choice(combined) for _ in range(length - len(pools))]
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return SecretStr("".join(chars))
