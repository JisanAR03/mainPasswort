"""The two digests sync compares copies by.

SHA-256 is how this app identifies a local file (data-model.md); MD5 is Drive's
own ``md5Checksum``. Neither is a security check here — the vault's own
encryption does that — so md5 is built with ``usedforsecurity=False``, which is
also what keeps it working on FIPS builds.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1024 * 1024


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def file_digests(path: Path) -> tuple[str, str]:
    """(sha256, md5) of a file, read once in chunks."""
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            sha256.update(chunk)
            md5.update(chunk)
    return sha256.hexdigest(), md5.hexdigest()
