"""Site matching rules from docs/specs/data-model.md ([S]).

Pure functions, no IO. These are the rules the bridge (M3, invariant I4) and
the popup both rely on; input is hostile, so every parse failure resolves to
"no match".
"""

from __future__ import annotations

from urllib.parse import urlsplit

_TRAILING_DOT = "."


def normalize_host(host: str) -> str:
    """Lower-case, convert to punycode, drop a trailing dot (rule 1)."""
    host = host.strip().lower().rstrip(_TRAILING_DOT)
    return host.encode("idna").decode("ascii")


def host_and_port_of_url(url: str) -> tuple[str, int | None] | None:
    """Return (normalized host, port) for http/https URLs; None otherwise."""
    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError on malformed ports
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = parts.hostname
    if not host:
        return None
    try:
        return normalize_host(host), port
    except UnicodeError:
        return None


def entry_matches(
    *,
    page_host: str,
    page_port: int | None,
    page_scheme: str,
    entry_host: str,
    entry_port: int | None,
    entry_scheme: str,
    match_subdomains: bool,
) -> bool:
    """Apply rules 2-5; True when the entry may be offered for the page."""
    try:
        host = normalize_host(page_host)
        target = normalize_host(entry_host)
    except UnicodeError:
        return False
    if host != target and not (match_subdomains and host.endswith("." + target)):
        return False
    if entry_port is not None and page_port != entry_port:
        return False
    entry_scheme = entry_scheme.lower()
    page_scheme = page_scheme.lower()
    if entry_scheme == "https" and page_scheme != "https":
        return False  # rule 4: never downgrade to an http page
    if entry_scheme == "http" and page_scheme != "http":
        return False  # rule 4: an http entry fills only on http
    return True


def match_urls(entry_urls: list[str], page_url: str, *, match_subdomains: bool = True) -> bool:
    """True when any entry URL matches the page URL under the site rules."""
    page = host_and_port_of_url(page_url)
    if page is None:
        return False
    page_host, page_port = page
    page_scheme = urlsplit(page_url).scheme.lower()
    for url in entry_urls:
        parsed = host_and_port_of_url(url)
        if parsed is None:
            continue
        entry_host, entry_port = parsed
        if entry_matches(
            page_host=page_host,
            page_port=page_port,
            page_scheme=page_scheme,
            entry_host=entry_host,
            entry_port=entry_port,
            entry_scheme=urlsplit(url).scheme.lower(),
            match_subdomains=match_subdomains,
        ):
            return True
    return False
