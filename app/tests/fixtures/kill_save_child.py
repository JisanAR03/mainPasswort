"""Child of the slow kill-save test: re-save the vault in a tight loop.

The parent kills this process at a random moment, 200 times. Every save goes
through storage.save_with_backup, so whichever moment is chosen, the vault
either holds the last complete save or a backup does (invariant I3).
"""

import sys
from pathlib import Path

from personal_vault.core import kdf, storage
from personal_vault.core.vault import open_vault
from pykeepass import create_database

WEAK_MEMORY_MIB = 8
WEAK_ITERATIONS = 1
SAVES = 200


def main() -> int:
    path = Path(sys.argv[1])
    backups = Path(sys.argv[2])
    password = sys.argv[3]
    path.parent.mkdir(parents=True, exist_ok=True)

    for index in range(SAVES):

        def writer(tmp: Path, index: int = index) -> None:
            kp = create_database(str(tmp), password=password)
            kdf.apply_kdf(
                kp,
                iterations=WEAK_ITERATIONS,
                memory_mib=WEAK_MEMORY_MIB,
                weak_override=True,
            )
            kp.add_group(kp.root_group, "Logins")
            kp.add_entry(kp.root_group, title=f"entry-{index}", username="u", password="p")
            kp.save()

        def verifier(tmp: Path) -> None:
            open_vault(tmp, password)

        storage.save_with_backup(path, writer, verifier, backups, keep_recent=3, keep_daily=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
