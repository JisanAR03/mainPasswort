# ADR-003 Browser integration: native messaging to a local socket

Status: Accepted
Date: 2026-10-15

## Context
The extension must not hold a copy of the vault.

## Decision
Extension → native host (stdio) → desktop app (local socket), with a pairing key per
profile. Click-to-fill only, top frame only, and unlock only in the desktop app.

## Consequences
The app must be running for the extension to work. No inline field icons in v1.
