# ADR-002 Stack: Python, PySide6, plain JavaScript

Status: Accepted
Date: 2026-10-15

## Context
One developer, AI-assisted, wants readable code and few dependencies.

## Decision
Python 3.12+ and PySide6 for the app; Manifest V3 for the extension, with no framework and
no npm packages.

## Consequences
Fast to build and easy to read. Python cannot wipe secrets from memory; this is documented
rather than worked around. Rust, Tauri and SQLite are rejected for v1 because they add
complexity without defeating the main threat, malware running as you.
