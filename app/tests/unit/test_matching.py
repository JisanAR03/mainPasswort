"""M1-05: site matching rules from docs/specs/data-model.md ([S])."""

from __future__ import annotations

import pytest
from personal_vault.core.matching import (
    entry_matches,
    host_and_port_of_url,
    match_urls,
    normalize_host,
)

pytestmark = pytest.mark.unit


def test_normalize_host_lower_and_trailing_dot() -> None:
    assert normalize_host("Example.COM.") == "example.com"


def test_normalize_host_punycode() -> None:
    assert normalize_host("bücher.example") == "xn--bcher-kva.example"


def test_host_and_port_of_url() -> None:
    assert host_and_port_of_url("https://example.com:8443/path") == ("example.com", 8443)
    assert host_and_port_of_url("http://example.com") == ("example.com", None)
    assert host_and_port_of_url("https://EXAMPLE.com.") == ("example.com", None)


def test_host_and_port_rejects_non_http_and_malformed() -> None:
    assert host_and_port_of_url("ftp://example.com") is None
    assert host_and_port_of_url("https://example.com:notaport/") is None
    assert host_and_port_of_url("not a url") is None
    assert host_and_port_of_url("") is None


def test_exact_host_matches() -> None:
    assert entry_matches(
        page_host="example.com",
        page_port=None,
        page_scheme="https",
        entry_host="example.com",
        entry_port=None,
        entry_scheme="https",
        match_subdomains=False,
    )


def test_subdomain_matches_only_with_flag() -> None:
    base = dict(
        page_host="mail.example.com",
        page_port=None,
        page_scheme="https",
        entry_host="example.com",
        entry_port=None,
        entry_scheme="https",
    )
    assert not entry_matches(**base, match_subdomains=False)
    assert entry_matches(**base, match_subdomains=True)


def test_lookalike_suffix_is_not_a_subdomain() -> None:
    assert not entry_matches(
        page_host="evil-example.com",
        page_port=None,
        page_scheme="https",
        entry_host="example.com",
        entry_port=None,
        entry_scheme="https",
        match_subdomains=True,
    )


def test_homoglyph_and_digit_substitution_do_not_match() -> None:
    # "paypa1.com" (digit) and "paypаl.com" (cyrillic 'а') are different hosts.
    for page_host in ("paypa1.com", "paypаl.com"):
        assert not entry_matches(
            page_host=page_host,
            page_port=None,
            page_scheme="https",
            entry_host="paypal.com",
            entry_port=None,
            entry_scheme="https",
            match_subdomains=False,
        )


def test_port_must_match_when_entry_has_one() -> None:
    base = dict(
        page_host="example.com",
        page_scheme="https",
        entry_host="example.com",
        entry_scheme="https",
        match_subdomains=False,
    )
    assert entry_matches(page_port=None, entry_port=None, **base)
    assert entry_matches(page_port=8443, entry_port=8443, **base)
    assert not entry_matches(page_port=None, entry_port=8443, **base)
    assert not entry_matches(page_port=443, entry_port=8443, **base)


def test_https_entry_never_offered_on_http_page() -> None:
    assert not entry_matches(
        page_host="example.com",
        page_port=None,
        page_scheme="http",
        entry_host="example.com",
        entry_port=None,
        entry_scheme="https",
        match_subdomains=False,
    )


def test_http_entry_only_on_http_page() -> None:
    assert entry_matches(
        page_host="example.com",
        page_port=None,
        page_scheme="http",
        entry_host="example.com",
        entry_port=None,
        entry_scheme="http",
        match_subdomains=False,
    )
    assert not entry_matches(
        page_host="example.com",
        page_port=None,
        page_scheme="https",
        entry_host="example.com",
        entry_port=None,
        entry_scheme="http",
        match_subdomains=False,
    )


def test_punycode_page_matches_unicode_entry() -> None:
    assert entry_matches(
        page_host="xn--bcher-kva.example",
        page_port=None,
        page_scheme="https",
        entry_host="bücher.example",
        entry_port=None,
        entry_scheme="https",
        match_subdomains=False,
    )


def test_match_urls_any_entry_url() -> None:
    assert match_urls(["https://example.com"], "https://example.com/login")
    assert not match_urls(["https://other.org"], "https://example.com")
    assert match_urls(["https://example.com"], "https://mail.example.com", match_subdomains=True)
    assert not match_urls(
        ["https://example.com"], "https://mail.example.com", match_subdomains=False
    )
