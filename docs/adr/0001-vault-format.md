# ADR-001 Vault format: KDBX 4 via pykeepass

Status: Accepted
Date: 2026-10-15

## Context
The brief forbids custom cryptography and demands recovery from damaged files.

## Decision
One KDBX 4 file per profile, read and written with pykeepass, using Argon2id key derivation.

## Consequences
KeePassXC and mobile KeePass apps can open every vault, which is the recovery plan.
pykeepass is GPL-3 and unaudited, so M0-02 must confirm its KDF and cipher output. If the
spike fails, fall back to a custom JSON envelope using `cryptography` (AES-256-GCM) and
`argon2-cffi`.
