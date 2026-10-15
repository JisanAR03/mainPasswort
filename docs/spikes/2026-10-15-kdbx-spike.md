# M0-02 spike report: KDBX 4 with pykeepass and KeePassXC

Date: 2026-10-15 · Machine: Windows 11 (the owner's daily OS) · pykeepass 4.2.0,
KeePassXC 2.7.12 (`keepassxc-cli`)

**Verdict: ADR-001 confirmed.** pykeepass can create KDBX 4 vaults with Argon2id at the D9
settings, and KeePassXC accepts and edits them. No fallback needed.

## What was tested, with results

| Check | Result |
| --- | --- |
| Create a vault with Argon2id, 128 MiB, parallelism 2, calibrated iterations | Works. pykeepass's blank database ships with Argon2**d**, so creation must patch the KDF parameter dictionary (`$UUID` → Argon2id, `V` → 0x13, `I`, `M`, `P`) before the first save. ~20 lines, no fork needed. |
| KeePassXC reads the result | `keepassxc-cli db-info` reports `KDF: Argon2id (12 rounds, 131072 KB)` and `Cipher: AES 256-bit`; `ls` and `add` work on the same file. |
| Calibrated iterations for ~1 s unlock | 12 rounds ≈ 0.87 s derivation, 0.96 s measured pykeepass unlock at 128 MiB, parallelism 2. Calibration loop: measure 1 and 2 rounds, extrapolate, clamp to ≥ 1. |
| Open a KeePassXC-made vault in pykeepass | Works, including AES-KDF vaults (`db-create` defaults). |
| Custom fields | `PM_MATCH_SUBDOMAINS` set via `set_custom_property`, read back after reopen. |
| Recycle Bin | `trash_entry()` creates the `Recycle Bin` group, persists `Meta/RecycleBinUUID`, and the entry survives reopen inside it. `delete_entry()` is a **permanent** delete — the app must never call it for the delete feature. |
| Deleted-object records | The `<DeletedObjects>` XML element survives pykeepass save/reopen untouched. pykeepass has no API for it; M6 tombstones will manipulate `payload.xml` directly. |
| Cipher | AES-256 (pykeepass's reliable default; KDBX 4.x). ChaCha20 not needed — the spec allowed either. |

## Findings that change the code plan

1. **KDF patching is required** (blank db is Argon2d). M1-02's `kdf.py` will do this in one
   `apply_kdf()` helper, and a test will assert `kdf_algorithm == "argon2id"` plus the
   exact `M`/`P`/`I` values on every created vault.
2. **Weak test KDF works the same way**: test fixtures patch `I`/`M` before saving, which is
   exactly the spec's "only the test fixture can pass the override" rule.
3. **`trash_entry`, never `delete_entry`, for delete.** The history entry count is capped at
   10 in M1-04.
4. **KeePassXC CLI `db-create` cannot pick Argon2id** (2.7.12 CLI has only `-t`; new vaults
   are AES-KDF). The KeePassXC **GUI** can, which is why the owner's GUI check below
   matters; pykeepass read both KDFs either way.

## pykeepass verification gaps (found by the M1-03 corruption tests)

Two pykeepass 4.2.0 gaps surfaced when flipping single bytes in a vault file. Both are
closed by a pre-KDF header check in `open_vault` (`_verify_kdbx_header`), which verifies
the signature, version, field layout and header SHA-256 (over the raw header, byte 0 to
the end of the fields) before pykeepass is called:

1. **KDF runs before the header checksum.** pykeepass derives the transformed key from the
   file's *unverified* KDF parameters, then checks the header SHA-256. Flipping a high byte
   of the Argon2 `I` or `M` values (offsets 148–150, 168 in a small vault) makes argon2 run
   effectively forever — `open()` hangs instead of raising.
2. **A flipped major-version byte opens silently.** construct's `Switch` defaults to `Pass`
   on an unmatched version, so the whole body (checksum, payload) is skipped and a garbage
   vault parses "successfully" (offsets 10–11).

`test_every_header_byte_flip_is_refused_before_kdf` flips every raw-header byte and asserts
`VaultCorrupted`; the 200-random-flip test covers the payload region.

## Owner steps (close the remaining "Done when" item)

- [ ] Open a pykeepass-created vault in the **KeePassXC GUI** and confirm
  Database → Database settings shows Argon2id, 128 MiB. (The CLI test above proves it; the
  GUI check is the spec's literal requirement.)

## Caveats

- The blank database's creation date shows as 2020 (pykeepass artifact; cosmetic).
- Argon2 at 128 MiB × 2 lanes needs ~256 MiB RAM per unlock; fine for desktop (Q3: no
  phone).
- Calibration drifts with machine load (0.077–0.090 s measured per round across runs).
  Calibrate at vault creation time, and re-check on the slowest supported desktop.
