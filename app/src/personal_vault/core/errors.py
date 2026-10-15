"""Vault error types. Messages never contain secrets (AGENTS rule 3)."""


class VaultError(Exception):
    """Base class for vault errors."""


class InvalidPassword(VaultError):
    """The master password is wrong (or the header does not verify)."""


class VaultCorrupted(VaultError):
    """The file is damaged and could not be read safely."""


class SchemaTooNewError(Exception):
    """A data file's schema_version is newer than this app understands."""
