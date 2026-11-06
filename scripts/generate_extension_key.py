"""Generate the extension keypair (once) and print the extension ID.

The ID is the Chromium extension ID for a manifest key: the SHA-256 of the
DER-encoded public key, first 16 bytes, each hex digit mapped 0-9a-f -> a-p.
The private key is kept OUTSIDE the extension folder (the browser warns about a key
file inside it) and is never committed: by default in a "PasswordManager-keys" folder
next to the repository, or wherever PV_KEY_PEM points. The public half goes into
extension/manifest.json (already done). Re-running with an existing key only prints the
ID — it never replaces the key, and it never edits the manifest.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_PEM = Path(os.environ.get("PV_KEY_PEM") or ROOT.parent / "PasswordManager-keys" / "key.pem")


def _run(*args: str) -> bytes:
    result = subprocess.run(args, capture_output=True, check=True)
    return result.stdout


def extension_id(public_der: bytes) -> str:
    digest = hashlib.sha256(public_der).digest()[:16]
    return "".join("abcdefghijklmnop"[int(c, 16)] for c in digest.hex())


def main() -> int:
    if not KEY_PEM.exists():
        KEY_PEM.parent.mkdir(parents=True, exist_ok=True)
        _run("openssl", "genrsa", "-out", str(KEY_PEM), "2048")
        print(f"wrote {KEY_PEM} (git-ignored: keep it private)")
    public_der = _run("openssl", "rsa", "-in", str(KEY_PEM), "-pubout", "-outform", "DER")
    print(f"extension id: {extension_id(public_der)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
