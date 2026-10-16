"""Sync errors, so the UI can say the right thing without parsing strings.

Everything here carries a code, never a token, a URL or a body: the UI shows
the code's sentence and the log holds nothing a secret could hide in.
"""

from __future__ import annotations


class SyncError(Exception):
    """Base class; every sync failure is one of these."""

    code = "sync_error"


class RetryableSyncError(SyncError):
    """No network, timeout, 429 or 5xx: the backoff schedule applies."""

    code = "retrying"


class NetworkError(RetryableSyncError):
    """The request never got an answer: timeout, DNS, no route."""

    code = "offline"


class RateLimited(RetryableSyncError):
    """HTTP 429: Drive is asking us to slow down."""

    code = "rate_limited"


class ServerError(RetryableSyncError):
    """HTTP 5xx: Drive's side is having a bad time."""

    code = "server_error"


class AuthExpired(SyncError):
    """HTTP 401: refresh the access token once, then retry."""

    code = "auth_expired"


class AccessDenied(SyncError):
    """HTTP 403: the token is fine but Drive refuses — scope, quota or sharing."""

    code = "access_denied"


class ReconnectRequired(SyncError):
    """The refresh token is gone or refused (invalid_grant); sign in again."""

    code = "reconnect"


class NotLinked(SyncError):
    """This profile has no Drive link yet."""

    code = "not_linked"


class RemoteUnreadable(SyncError):
    """A download did not decrypt, or did not match what Drive reported."""

    code = "remote_unreadable"


class RemoteMissing(SyncError):
    """The file we synced against is gone or trashed: ask, never recreate."""

    code = "remote_missing"


class TokenScopeError(SyncError):
    """The stored token was not minted for drive.file."""

    code = "token_scope"


class ClientSecretMissing(SyncError):
    """client_secret.json is absent, unreadable, or not a Desktop-app client."""

    code = "client_secret"
