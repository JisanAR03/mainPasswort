# References

## Source material

- **Personal Password Manager: Pre-Build Design Pack**, draft v0.1, dated 2026-10-15
  (38 pages). This is the full project specification. It is kept locally and is not committed
  to this repository; the documents in `docs/` carry its content. Personal names that appear
  in it have been left out of these docs on purpose.

## Sources cited by the design pack

The spec says these facts were checked on 15 October 2026 and will be re-verified in the M0
spikes.

- Chrome native messaging docs: the 1 MB limit on host-to-browser messages, and
  `allowed_origins`.
  <https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging>
- Google Drive OAuth scope tiers: `drive.file` is non-sensitive.
  <https://developers.google.com/workspace/drive/api/guides/api-specific-auth>
- Nango guide to Google OAuth apps: refresh tokens expire after 7 days in Testing mode. See
  also Google's own note on refresh token expiration:
  <https://developers.google.com/identity/protocols/oauth2#expiration>
- gogcli pull request 929: Drive v3 does not expose the ETag needed for an atomic
  conditional upload.
- Gentoo pykeepass package: GPL-3 license and dependencies.
- openSUSE pykeepass changelog: Argon2id support and `create_database()`.

## Libraries and tools

| Name | Used for | Link |
| --- | --- | --- |
| pykeepass | Reading and writing KDBX 4 vaults | <https://github.com/libkeepass/pykeepass> |
| KeePassXC | Emergency reader, recovery, `keepassxc-cli` compatibility tests | <https://keepassxc.org/> |
| PySide6 (Qt for Python) | Desktop UI and local socket | <https://doc.qt.io/qtforpython-6/> |
| platformdirs | Per-OS app data folder | <https://github.com/tox-dev/platformdirs> |
| google-auth-oauthlib | Desktop OAuth flow with PKCE | <https://github.com/googleapis/google-auth-library-python-oauthlib> |
| uv | Python version, virtual env, lock file | <https://docs.astral.sh/uv/> |
| ruff | Lint and format | <https://docs.astral.sh/ruff/> |
| mypy | Type checks | <https://mypy.readthedocs.io/> |
| pytest | Test runner | <https://docs.pytest.org/> |
| Hypothesis | Property and fuzz tests | <https://hypothesis.readthedocs.io/> |
| pytest-qt | UI tests | <https://pytest-qt.readthedocs.io/> |
| Playwright for Python | Extension end-to-end tests | <https://playwright.dev/python/> |
| import-linter | Layer rule enforcement | <https://import-linter.readthedocs.io/> |
| bandit | Python security lint | <https://bandit.readthedocs.io/> |
| pip-audit | Vulnerable dependency checks | <https://github.com/pypa/pip-audit> |
| gitleaks | Secret scanning | <https://github.com/gitleaks/gitleaks> |
| PyInstaller | Packaging (M6) | <https://pyinstaller.org/> |

## Platform documentation

- KDBX 4 file format: <https://keepass.info/help/kb/kdbx_4.html>
- Chrome extensions, `activeTab`:
  <https://developer.chrome.com/docs/extensions/develop/concepts/activeTab>
- Chrome extensions, `chrome.scripting`:
  <https://developer.chrome.com/docs/extensions/reference/api/scripting>
- Google OAuth 2.0 for desktop apps:
  <https://developers.google.com/identity/protocols/oauth2/native-app>
- Google Drive API v3, files and revisions:
  <https://developers.google.com/workspace/drive/api/reference/rest/v3>

## Conventions

- Keep a Changelog: <https://keepachangelog.com/en/1.1.0/>
- Conventional Commits: <https://www.conventionalcommits.org/>
