"""The vault features the audit found missing (docs/tasks/FEAT-02-audit-fixes-and-features.md):
changing the master password, the Recycle Bin, backups, importing, an entry's
history, one-time codes, the password-health report, merging a conflict, and the
settings behind them. Each test drives the real extension in a real browser; where
another program can check the result (pykeepass, KeePassXC) it does."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from conftest import EXT_PASSWORD, Ext, SeededVault
from fixtures.weak_vault import build_weak_vault, make_login
from personal_vault.core.models import SecretStr
from personal_vault.core.vault import VaultSession
from playwright.sync_api import BrowserContext, Page
from pykeepass import PyKeePass
from support import (
    no_extension_frame,
    open_login_page,
    prompt_frame,
    submit_login,
)

pytestmark = pytest.mark.e2e

NEW_PASSWORD = "a brand new master passphrase"
CANARY = "CANARY-5c2e81"


def _cli() -> str | None:
    found = os.environ.get("KEEPASSXC_CLI") or shutil.which("keepassxc-cli")
    if found:
        return found
    default = Path("C:/Program Files/KeePassXC/keepassxc-cli.exe")
    return str(default) if default.exists() else None


def _export(ext: Ext) -> bytes:
    return base64.b64decode(ext.ok("ext_export")["bytes"])


def _drive_bytes(ext: Ext, profile: str) -> bytes:
    with ext.google.lock:
        return ext.google.vault_of(profile).content


def _write(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / f"{uuid.uuid4().hex}.kdbx"
    path.write_bytes(data)
    return path


def _open(tmp_path: Path, data: bytes, password: str) -> PyKeePass:
    return PyKeePass(str(_write(tmp_path, data)), password=password)


def _titles(ext: Ext) -> list[str]:
    return sorted(e["title"] for e in ext.ok("ext_list", {"query": ""})["entries"])


def _entry_id(ext: Ext, title: str) -> str:
    return next(
        e["id"] for e in ext.ok("ext_list", {"query": ""})["entries"] if e["title"] == title
    )


def _connect(ext: Ext, profile: str) -> None:
    ext.ok("ext_connect")
    ext.wait_status(profile, {"synced"})


# --- one-time codes (TOTP) --------------------------------------------------------------------

RFC_SEEDS = {
    "SHA1": b"12345678901234567890",
    "SHA256": b"12345678901234567890123456789012",
    "SHA512": b"1234567890123456789012345678901234567890123456789012345678901234",
}
# RFC 6238 appendix B: time, then the 8-digit code for SHA-1, SHA-256 and SHA-512
RFC_VECTORS = [
    (59, "94287082", "46119246", "90693936"),
    (1111111109, "07081804", "68084774", "25091201"),
    (1111111111, "14050471", "67062674", "99943326"),
    (1234567890, "89005924", "91819424", "93441116"),
    (2000000000, "69279037", "90698825", "38618901"),
    (20000000000, "65353130", "77737706", "47863826"),
]


def test_totp_matches_every_rfc_6238_test_vector(control_page: Page) -> None:
    uris = {
        algorithm: (
            f"otpauth://totp/rfc?secret={base64.b32encode(seed).decode().rstrip('=')}"
            f"&digits=8&algorithm={algorithm}"
        )
        for algorithm, seed in RFC_SEEDS.items()
    }
    got = control_page.evaluate(
        """async ([uris, times]) => {
          const m = await import(chrome.runtime.getURL('totp.js'));
          const out = [];
          for (const t of times) {
            const row = [t];
            for (const algorithm of ['SHA1', 'SHA256', 'SHA512']) {
              row.push((await m.totpCode(uris[algorithm], t * 1000)).code);
            }
            out.push(row);
          }
          return out;
        }""",
        [uris, [v[0] for v in RFC_VECTORS]],
    )
    assert [tuple(row) for row in got] == RFC_VECTORS


def test_totp_reads_secrets_the_way_apps_write_them(control_page: Page) -> None:
    results = control_page.evaluate(
        """async () => {
          const m = await import(chrome.runtime.getURL('totp.js'));
          const at = 59 * 1000;
          const bare = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'; // the RFC seed, 6 digits by default
          return {
            bare: (await m.totpCode(bare, at)).code,
            spaced: (await m.totpCode('gezd gnbv-gy3t qojq gezd gnbv gy3t qojq', at)).code,
            padded: (await m.totpCode(bare + '====', at)).code,
            period60: (await m.totpCode('otpauth://totp/x?secret=' + bare + '&period=60', at))
              .period,
            hotp: m.parseOtp('otpauth://hotp/x?secret=' + bare + '&counter=1'),
            steam: m.parseOtp('otpauth://totp/x?secret=' + bare + '&encoder=steam'),
            notBase32: m.parseOtp('not a secret!'),
            tooShortDigits: m.parseOtp('otpauth://totp/x?secret=' + bare + '&digits=4'),
          };
        }"""
    )
    assert results["bare"] == "287082"  # the last six digits of the 8-digit vector
    assert results["spaced"] == results["bare"] == results["padded"]
    assert results["period60"] == 60
    assert results["hotp"] is None and results["steam"] is None
    assert results["notBase32"] is None and results["tooShortDigits"] is None


def test_a_login_with_a_totp_secret_gives_codes_that_keepassxc_agrees_with(
    ext: Ext, tmp_path: Path
) -> None:
    ext.create_profile("Personal")
    entry = ext.add_login(title="With 2FA", otp="JBSWY3DPEHPK3PXP")
    stored = ext.ok("ext_get", {"entryId": entry})["entry"]
    assert stored["otp"] == "otpauth://totp/With%202FA?secret=JBSWY3DPEHPK3PXP"
    summary = next(e for e in ext.ok("ext_list", {"query": ""})["entries"] if e["id"] == entry)
    assert summary["has_totp"] is True

    code = ext.ok("ext_totp", {"entryId": entry})
    assert re.fullmatch(r"\d{6}", code["code"]) and 1 <= code["remaining"] <= 30

    exported = _export(ext)
    assert (
        _open(tmp_path, exported, EXT_PASSWORD).find_entries(title="With 2FA", first=True).otp
        == stored["otp"]
    )
    cli = _cli()
    if cli:
        path = _write(tmp_path, exported)
        for _ in range(3):  # a 30-second window may roll over between the two reads
            ours = ext.ok("ext_totp", {"entryId": entry})["code"]
            shown = subprocess.run(
                [cli, "show", "-t", str(path), "Logins/With 2FA"],
                input=EXT_PASSWORD + "\n",
                capture_output=True,
                text=True,
            )
            assert shown.returncode == 0, shown.stderr
            if shown.stdout.strip().splitlines()[-1] == ours:
                break
            time.sleep(1)
        else:
            raise AssertionError("KeePassXC and the extension never agreed on the code")


def test_a_totp_secret_that_is_not_one_is_refused_and_a_login_without_one_says_so(ext: Ext) -> None:
    ext.create_profile("Personal")
    bad = ext.call(
        "ext_save_entry",
        {"entry": {"title": "Bad", "username": "u", "password": "p", "otp": "not base32 !!"}},
    )
    assert bad["ok"] is False and bad["error"]["code"] == "invalid"
    plain = ext.add_login(title="Plain")
    assert ext.call("ext_totp", {"entryId": plain})["error"]["code"] == "no_totp"
    # a secret can be removed again by saving the field empty
    with_otp = ext.add_login(title="Temp", otp="JBSWY3DPEHPK3PXP")
    saved = ext.ok("ext_get", {"entryId": with_otp})["entry"]
    ext.ok("ext_save_entry", {"entry": {**saved, "otp": ""}})
    assert ext.ok("ext_get", {"entryId": with_otp})["entry"]["otp"] == ""


def test_the_popup_copies_the_one_time_code_of_the_pages_own_login_only(
    browser: BrowserContext, ext: Ext, page_server: str
) -> None:
    from support import open_popup

    ext.create_profile("Personal")
    here = ext.add_login(title="Here", otp="JBSWY3DPEHPK3PXP", urls=[f"{page_server}/login.html"])
    elsewhere = ext.add_login(
        title="Elsewhere", otp="JBSWY3DPEHPK3PXP", urls=["https://other.example/"]
    )
    open_login_page(browser, f"{page_server}/login.html")
    popup = open_popup(browser)
    popup.wait_for_selector("#matches .match", timeout=30_000)
    assert popup.locator("#matches .match button", has_text="Copy code").count() == 1
    # the engine itself refuses a code for a login that is not this page's
    refused = popup.evaluate(
        "([id, url]) => chrome.runtime.sendMessage({ type: 'get_totp', entryId: id, url })",
        [elsewhere, f"{page_server}/login.html"],
    )
    assert refused["ok"] is False
    allowed = popup.evaluate(
        "([id, url]) => chrome.runtime.sendMessage({ type: 'get_totp', entryId: id, url })",
        [here, f"{page_server}/login.html"],
    )
    assert allowed["ok"] and re.fullmatch(r"\d{6}", allowed["result"]["code"])


# --- change the master password ---------------------------------------------------------------


def test_changing_the_master_password_rekeys_the_vault(ext: Ext, tmp_path: Path) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Keep me", password="kept password", urls=["https://keep.example/"])

    wrong = ext.call("ext_change_password", {"password": "not it", "newPassword": NEW_PASSWORD})
    assert wrong["ok"] is False and wrong["error"]["code"] == "bad_password"
    short = ext.call("ext_change_password", {"password": EXT_PASSWORD, "newPassword": "short"})
    assert short["ok"] is False and short["error"]["code"] == "password_too_short"
    assert _open(tmp_path, _export(ext), EXT_PASSWORD), "a refused change left the old key"

    ext.ok("ext_change_password", {"password": EXT_PASSWORD, "newPassword": NEW_PASSWORD})
    assert _titles(ext) == ["Keep me"], "still unlocked, nothing lost"
    exported = _export(ext)
    assert _open(tmp_path, exported, NEW_PASSWORD).find_entries(title="Keep me", first=True)
    with pytest.raises(Exception):  # noqa: B017, PT011 - pykeepass raises its own credentials error
        _open(tmp_path, exported, EXT_PASSWORD)
    cli = _cli()
    if cli:
        path = _write(tmp_path, exported)
        shown = subprocess.run(
            [cli, "ls", "-R", str(path)], input=NEW_PASSWORD + "\n", capture_output=True, text=True
        )
        assert shown.returncode == 0, shown.stderr
        assert "Keep me" in shown.stdout

    ext.ok("ext_lock")
    old = ext.call("ext_unlock", {"profileId": profile, "password": EXT_PASSWORD})
    assert old["ok"] is False and old["error"]["code"] == "bad_password"
    ext.ok("ext_unlock", {"profileId": profile, "password": NEW_PASSWORD})
    assert _titles(ext) == ["Keep me"]


def test_the_new_password_survives_the_engine_document_closing(ext: Ext) -> None:
    """The unlock record holds the new key: after the engine document is gone the
    worker reopens the vault with it (and a stale key would lock everything)."""
    ext.create_profile("Personal")
    ext.add_login(title="Keep me")
    ext.ok("ext_change_password", {"password": EXT_PASSWORD, "newPassword": NEW_PASSWORD})
    ext.control.evaluate(
        "async () => {"
        " const docs = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });"
        " if (docs.length) await chrome.offscreen.closeDocument(); }"
    )
    assert _titles(ext) == ["Keep me"]
    assert ext.state()["unlocked"] is not None


def test_a_changed_password_reaches_drive(ext: Ext, tmp_path: Path) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Synced")
    _connect(ext, profile)
    revisions = len(ext.google.vault_of(profile).revisions)
    ext.ok("ext_change_password", {"password": EXT_PASSWORD, "newPassword": NEW_PASSWORD})
    ext.wait_status(profile, {"synced"})
    waited = 0
    while len(ext.google.vault_of(profile).revisions) == revisions and waited < 30_000:
        ext.control.wait_for_timeout(250)
        waited += 250
    remote = _drive_bytes(ext, profile)
    assert _open(tmp_path, remote, NEW_PASSWORD).find_entries(title="Synced", first=True)
    with pytest.raises(Exception):  # noqa: B017, PT011
        _open(tmp_path, remote, EXT_PASSWORD)


def test_a_password_changed_on_another_device_is_taken_with_the_new_password(
    ext: Ext, tmp_path: Path
) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Before")
    _connect(ext, profile)

    # "another device" changes the master password and syncs
    other = PyKeePass(str(_write(tmp_path, _drive_bytes(ext, profile))), password=EXT_PASSWORD)
    other.password = NEW_PASSWORD
    other.save()
    ext.google.write_from_other_device(profile, Path(other.filename).read_bytes())

    ext.ok("ext_sync_now")
    status = ext.wait_status(profile, {"unreadable"})
    assert "enter the new one" in status["message"]
    before = _export(ext)

    wrong = ext.ok("ext_choose", {"choice": "take_theirs", "password": "not the new one"})
    assert wrong["state"] == "unreadable"
    assert _export(ext) == before, "a wrong password adopts nothing"

    done = ext.ok("ext_choose", {"choice": "take_theirs", "password": NEW_PASSWORD})
    assert done["state"] == "synced"
    assert _titles(ext) == ["Before"]
    ext.ok("ext_lock")
    ext.ok(
        "ext_unlock", {"profileId": profile, "password": NEW_PASSWORD}
    )  # the new key is the vault's now


# --- Recycle Bin ------------------------------------------------------------------------------


def test_the_recycle_bin_restores_deletes_for_good_and_empties(ext: Ext, tmp_path: Path) -> None:
    ext.create_profile("Personal")
    a = ext.add_login(title="Alpha", password="alpha pw")
    b = ext.add_login(title="Bravo", password="bravo pw")
    ext.add_login(title="Charlie", password="charlie pw")
    ext.ok("ext_delete_entry", {"entryId": a})
    ext.ok("ext_delete_entry", {"entryId": b})
    assert _titles(ext) == ["Charlie"]
    assert sorted(e["title"] for e in ext.ok("ext_bin_list")["entries"]) == ["Alpha", "Bravo"]

    ext.ok("ext_bin_restore", {"entryId": a})
    assert _titles(ext) == ["Alpha", "Charlie"]
    assert ext.ok("ext_get", {"entryId": a})["entry"]["password"] == "alpha pw"
    assert [e["title"] for e in ext.ok("ext_bin_list")["entries"]] == ["Bravo"]

    ext.ok("ext_bin_delete", {"entryId": b})
    assert ext.ok("ext_bin_list")["entries"] == []
    on_disk = {e.title for e in _open(tmp_path, _export(ext), EXT_PASSWORD).entries}
    assert on_disk == {"Alpha", "Charlie"}, "deleted for good means gone from the file"

    charlie = _entry_id(ext, "Charlie")
    ext.ok("ext_delete_entry", {"entryId": charlie})
    assert ext.ok("ext_bin_empty")["removed"] == 1
    assert ext.ok("ext_bin_empty")["removed"] == 0
    assert ext.call("ext_bin_restore", {"entryId": "nothing-here"})["error"]["code"] == "not_found"


def test_a_login_deleted_for_good_does_not_come_back_through_a_merge(
    ext: Ext, tmp_path: Path
) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Keeper")
    doomed = ext.add_login(title="Doomed")
    _connect(ext, profile)

    theirs = PyKeePass(str(_write(tmp_path, _drive_bytes(ext, profile))), password=EXT_PASSWORD)
    group = theirs.find_groups(name="Logins", first=True)
    theirs.add_entry(group, "Theirs", "them", "their pw")
    theirs.save()
    ext.google.write_from_other_device(profile, Path(theirs.filename).read_bytes())

    ext.ok("ext_delete_entry", {"entryId": doomed})
    ext.ok("ext_bin_delete", {"entryId": doomed})  # gone for good, on this side
    ext.wait_status(profile, {"conflict"})
    ext.ok("ext_choose", {"choice": "merge"})
    ext.wait_status(profile, {"synced"})
    assert _titles(ext) == ["Keeper", "Theirs"], "the deleted login stayed deleted"


# --- backups ----------------------------------------------------------------------------------


def test_an_earlier_backup_can_be_restored_and_the_restore_undone(ext: Ext) -> None:
    ext.create_profile("Personal")
    for title in ("One", "Two", "Three"):
        ext.add_login(title=title)
    backups = ext.ok("ext_backup_list")["backups"]
    assert len(backups) == 3 and all(b["size"] > 0 for b in backups)

    # newest first: [One, Two], [One], [nothing]; restore the one holding only "One"
    ext.ok("ext_restore_backup", {"backupId": backups[1]["id"]})
    assert _titles(ext) == ["One"]
    undo = ext.ok("ext_backup_list")["backups"][0]  # the vault just replaced
    ext.ok("ext_restore_backup", {"backupId": undo["id"]})
    assert _titles(ext) == ["One", "Three", "Two"]


def test_a_backup_from_before_a_password_change_needs_the_old_password_and_takes_the_new_key(
    ext: Ext,
) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Old")
    ext.ok("ext_change_password", {"password": EXT_PASSWORD, "newPassword": NEW_PASSWORD})
    ext.add_login(title="After")
    backups = ext.ok("ext_backup_list")["backups"]
    # newest first: [Old under the NEW key], [Old under the OLD key], [nothing]
    under_old_key = backups[1]["id"]

    without = ext.call("ext_restore_backup", {"backupId": under_old_key})
    assert without["error"]["code"] == "backup_password"
    wrong = ext.call("ext_restore_backup", {"backupId": under_old_key, "password": "not it"})
    assert wrong["error"]["code"] == "bad_password"
    assert _titles(ext) == ["After", "Old"], "a refused restore changed nothing"

    ext.ok("ext_restore_backup", {"backupId": under_old_key, "password": EXT_PASSWORD})
    assert _titles(ext) == ["Old"]
    ext.ok("ext_lock")  # the restored vault is under the CURRENT key
    assert ext.call("ext_unlock", {"profileId": profile, "password": EXT_PASSWORD})["ok"] is False
    ext.ok("ext_unlock", {"profileId": profile, "password": NEW_PASSWORD})
    assert _titles(ext) == ["Old"]


# --- import -----------------------------------------------------------------------------------

CHROME_CSV = (
    "\ufeffname,url,username,password,note\r\n"
    'Example,https://example.com/login?x=1,ann@example.com,"p,w""1","line1\nline2"\r\n'
    "No scheme,shop.example.org,bob,pw2,\r\n"
    "App only,androidapp://com.example.app,carl,pw3,\r\n"
    ",,,,\r\n"
)


def test_import_csv_reads_quotes_newlines_bare_sites_and_skips_what_it_cannot_use(ext: Ext) -> None:
    ext.create_profile("Personal")
    result = ext.ok("ext_import_csv", {"text": CHROME_CSV})
    assert result == {"added": 3, "duplicates": 0, "skipped": 1}
    by_title = {
        e["title"]: ext.ok("ext_get", {"entryId": e["id"]})["entry"]
        for e in ext.ok("ext_list", {"query": ""})["entries"]
    }
    example = by_title["Example"]
    assert example["urls"] == ["https://example.com/"], "the site, not the page with its query"
    assert example["username"] == "ann@example.com"
    assert example["password"] == 'p,w"1'
    assert example["notes"] == "line1\nline2"
    assert example["tags"] == ["imported"]
    assert by_title["No scheme"]["urls"] == ["https://shop.example.org/"]
    assert by_title["App only"]["urls"] == [], "a non-web address cannot match a page"

    again = ext.ok("ext_import_csv", {"text": CHROME_CSV})
    assert again == {"added": 0, "duplicates": 3, "skipped": 1}


@pytest.mark.parametrize(
    ("label", "text", "expected"),
    [
        (
            "firefox",
            "url,username,password,httpRealm,formActionOrigin,guid,timeCreated,timeLastUsed,timePasswordChanged\n"
            "https://fox.example,fox@example.com,fox-pw,,,{guid},1,2,3\n",
            ("fox.example", "fox@example.com", "fox-pw", ["https://fox.example/"]),
        ),
        (
            "bitwarden",
            "folder,favorite,type,name,notes,fields,reorg,login_uri,login_username,login_password,login_totp\n"
            ",,login,Bit Site,a note,,,https://bit.example/x,bit@example.com,bit-pw,JBSWY3DPEHPK3PXP\n",
            ("Bit Site", "bit@example.com", "bit-pw", ["https://bit.example/"]),
        ),
        (
            "keepassxc",
            '"Group","Title","Username","Password","URL","Notes","TOTP"\n'
            '"Root","KPX Site","kpx@example.com","kpx-pw","https://kpx.example","","JBSWY3DPEHPK3PXP"\n',
            ("KPX Site", "kpx@example.com", "kpx-pw", ["https://kpx.example/"]),
        ),
        (
            "lastpass",
            "url,username,password,totp,extra,name,grouping,fav\n"
            "https://lp.example,lp@example.com,lp-pw,,my note,LP Site,,0\n",
            ("LP Site", "lp@example.com", "lp-pw", ["https://lp.example/"]),
        ),
    ],
)
def test_import_csv_knows_the_other_managers_headers(
    ext: Ext, label: str, text: str, expected: tuple[str, str, str, list[str]]
) -> None:
    ext.create_profile("Personal")
    assert ext.ok("ext_import_csv", {"text": text})["added"] == 1, label
    entry = ext.ok("ext_list", {"query": ""})["entries"][0]
    full = ext.ok("ext_get", {"entryId": entry["id"]})["entry"]
    assert (full["title"], full["username"], full["password"], full["urls"]) == expected
    if label in ("bitwarden", "keepassxc"):
        assert ext.ok("ext_totp", {"entryId": entry["id"]})[
            "code"
        ].isdigit()  # the secret came along


def test_import_csv_refuses_what_it_cannot_read_and_keeps_no_plaintext(ext: Ext) -> None:
    ext.create_profile("Personal")
    no_password_column = ext.call("ext_import_csv", {"text": "foo,bar\n1,2\n"})
    assert no_password_column["error"]["code"] == "import_unrecognized"
    unclosed = ext.call("ext_import_csv", {"text": 'name,password\n"never closed,x\n'})
    assert unclosed["error"]["code"] == "import_malformed"
    empty = ext.call("ext_import_csv", {"text": ""})
    assert empty["error"]["code"] == "import_too_large"
    assert _titles(ext) == [], "a refused file changed nothing"

    ext.ok("ext_import_csv", {"text": f"name,username,password\nCanary,u,{CANARY}\n"})
    assert CANARY not in ext.dump_storage(), "an import writes the encrypted vault only"


def test_import_kdbx_brings_logins_not_the_desktop_secrets_or_the_bin(
    ext: Ext, tmp_path: Path
) -> None:
    source = build_weak_vault(tmp_path / "source.kdbx", password="source password")
    session = VaultSession.open(source, "source password", tmp_path / "backups")
    session.add(
        make_login(
            title="From file",
            username="file-user",
            password=SecretStr("file password"),
            urls=["https://file.example/login?a=1"],
            tags=["work"],
        )
    )
    gone = make_login(title="Was deleted", password=SecretStr("deleted pw"))
    session.add(gone)
    session.delete(gone.id)
    session.set_app_value("browser-pairing", f"{CANARY}-pairing")
    session.save()
    session.close()

    ext.create_profile("Personal")
    wrong = ext.call(
        "ext_import_kdbx",
        {"bytes": base64.b64encode(source.read_bytes()).decode(), "password": "not it"},
    )
    assert wrong["error"]["code"] == "bad_password"
    result = ext.ok(
        "ext_import_kdbx",
        {"bytes": base64.b64encode(source.read_bytes()).decode(), "password": "source password"},
    )
    assert result["added"] == 1
    assert _titles(ext) == ["From file"], "neither the bin nor the hidden .app group came along"
    entry = ext.ok("ext_get", {"entryId": _entry_id(ext, "From file")})["entry"]
    assert entry["urls"] == ["https://file.example/"] and entry["password"] == "file password"
    assert entry["tags"] == ["work", "imported"]
    assert f"{CANARY}-pairing" not in ext.dump_storage()
    assert (
        ext.ok(
            "ext_import_kdbx",
            {
                "bytes": base64.b64encode(source.read_bytes()).decode(),
                "password": "source password",
            },
        )["duplicates"]
        == 1
    )


# --- an entry's history -----------------------------------------------------------------------


def test_an_entrys_earlier_versions_can_be_viewed_and_restored(ext: Ext) -> None:
    ext.create_profile("Personal")
    entry = ext.add_login(title="History", username="h@example.com", password="v1")
    for password in ("v2", "v3"):
        saved = ext.ok("ext_get", {"entryId": entry})["entry"]
        ext.ok("ext_save_entry", {"entry": {**saved, "password": password}})

    versions = ext.ok("ext_history_list", {"entryId": entry})["versions"]
    assert len(versions) == 2  # v1 and v2: the current one (v3) is not "earlier"
    oldest = versions[-1]
    assert (
        ext.ok("ext_history_get", {"entryId": entry, "index": oldest["index"]})["entry"]["password"]
        == "v1"
    )
    assert (
        ext.ok("ext_history_get", {"entryId": entry, "index": versions[0]["index"]})["entry"][
            "password"
        ]
        == "v2"
    )

    ext.ok("ext_history_restore", {"entryId": entry, "index": oldest["index"]})
    assert ext.ok("ext_get", {"entryId": entry})["entry"]["password"] == "v1"
    kept = [
        ext.ok("ext_history_get", {"entryId": entry, "index": v["index"]})["entry"]["password"]
        for v in ext.ok("ext_history_list", {"entryId": entry})["versions"]
    ]
    assert sorted(kept) == ["v1", "v2", "v3"], "restoring keeps what was current in the list"
    assert (
        ext.call("ext_history_get", {"entryId": entry, "index": 99})["error"]["code"] == "not_found"
    )


# --- password health --------------------------------------------------------------------------


def test_the_health_report_finds_weak_and_reused_passwords_without_revealing_any(ext: Ext) -> None:
    ext.create_profile("Personal")
    shared = "A good long shared passphrase 91!"
    ids = {
        "common": ext.add_login(title="Common", password="password"),
        "short": ext.add_login(title="Short", password="Ab3$x"),
        "weak": ext.add_login(title="Weak", password="aaaaaaaaaaaaaaaa"),
        "reuse_a": ext.add_login(title="Reuse A", password=shared),
        "reuse_b": ext.add_login(title="Reuse B", password=shared),
        "strong": ext.add_login(title="Strong", password="Xk9#mQ2$vL7@pR4!zT6&"),
    }
    reply = ext.call("ext_report")
    assert reply["ok"]
    report = reply["result"]
    assert report["total"] == 6
    weak = {w["title"]: w["reason"] for w in report["weak"]}
    assert weak == {"Common": "common", "Short": "short", "Weak": "weak"}
    assert [sorted(e["title"] for e in group) for group in report["reused"]] == [
        ["Reuse A", "Reuse B"]
    ]
    assert report["old"] == []
    assert ids["strong"] not in {w["id"] for w in report["weak"]}
    text = json.dumps(reply)
    for secret in ("password", "Ab3$x", "aaaaaaaaaaaaaaaa", shared, "Xk9#mQ2$vL7@pR4!zT6&"):
        assert f'"{secret}"' not in text and secret not in text.replace("password", "")


# --- merge both copies ------------------------------------------------------------------------


def test_a_conflict_can_be_merged_so_both_sides_keep_their_logins(ext: Ext, tmp_path: Path) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Shared")
    _connect(ext, profile)

    theirs = PyKeePass(str(_write(tmp_path, _drive_bytes(ext, profile))), password=EXT_PASSWORD)
    theirs.add_entry(
        theirs.find_groups(name="Logins", first=True), "Their Login", "them", "their pw"
    )
    theirs.save()
    ext.google.write_from_other_device(profile, Path(theirs.filename).read_bytes())
    head = ext.google.vault_of(profile).revisions[-1].id

    ext.add_login(title="Mine")
    status = ext.wait_status(profile, {"conflict"})
    assert "merge them" in status["message"]
    assert ext.google.vault_of(profile).revisions[-1].id == head, "nothing was overwritten (I6)"

    ext.ok("ext_choose", {"choice": "merge"})
    ext.wait_status(profile, {"synced"})
    assert _titles(ext) == ["Mine", "Shared", "Their Login"]
    on_drive = {e.title for e in _open(tmp_path, _drive_bytes(ext, profile), EXT_PASSWORD).entries}
    assert {"Mine", "Shared", "Their Login"} <= on_drive
    cli = _cli()
    if cli:
        path = _write(tmp_path, _drive_bytes(ext, profile))
        shown = subprocess.run(
            [cli, "ls", "-R", str(path)], input=EXT_PASSWORD + "\n", capture_output=True, text=True
        )
        assert shown.returncode == 0, shown.stderr
        assert "Their Login" in shown.stdout


def test_merging_when_drive_moved_on_again_asks_again_instead_of_overwriting(
    ext: Ext, tmp_path: Path
) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Shared")
    _connect(ext, profile)
    first = PyKeePass(str(_write(tmp_path, _drive_bytes(ext, profile))), password=EXT_PASSWORD)
    first.add_entry(first.find_groups(name="Logins", first=True), "Their First", "them", "pw")
    first.save()
    ext.google.write_from_other_device(profile, Path(first.filename).read_bytes())
    ext.add_login(title="Mine")
    ext.wait_status(profile, {"conflict"})

    # Drive changes AGAIN before the owner clicks Merge: that newest copy was never seen
    second = PyKeePass(str(_write(tmp_path, _drive_bytes(ext, profile))), password=EXT_PASSWORD)
    second.add_entry(second.find_groups(name="Logins", first=True), "Their Second", "them", "pw")
    second.save()
    ext.google.write_from_other_device(profile, Path(second.filename).read_bytes())
    head = ext.google.vault_of(profile).revisions[-1].id

    ext.ok("ext_choose", {"choice": "merge"})
    status = ext.wait_status(profile, {"conflict", "synced"})
    assert status["state"] == "conflict", "the unseen copy is a new conflict, never overwritten"
    assert ext.google.vault_of(profile).revisions[-1].id == head


# --- settings ---------------------------------------------------------------------------------


def test_settings_are_checked_remembered_and_applied(ext: Ext) -> None:
    profile = ext.create_profile("Personal")
    defaults = ext.state()["settings"]
    assert defaults["lockAfterIdleMinutes"] == 0 and defaults["unlockHours"] == 6
    assert defaults["generator"] == {
        "length": 20,
        "upper": True,
        "lower": True,
        "digits": True,
        "symbols": True,
        "excludeLookalikes": True,
    }

    ext.ok("ext_settings", {"lockAfterIdleMinutes": 7, "unlockHours": 12})  # not offered: ignored
    assert ext.state()["settings"]["lockAfterIdleMinutes"] == 0
    assert ext.state()["settings"]["unlockHours"] == 6

    ext.ok(
        "ext_settings",
        {
            "lockAfterIdleMinutes": 15,
            "unlockHours": 2,
            "generator": {
                "length": 32,
                "upper": True,
                "lower": True,
                "digits": False,
                "symbols": False,
                "excludeLookalikes": False,
            },
        },
    )
    settings = ext.state()["settings"]
    assert settings["lockAfterIdleMinutes"] == 15 and settings["unlockHours"] == 2
    assert settings["generator"]["length"] == 32 and settings["generator"]["digits"] is False

    # a shorter unlock is honoured the next time you unlock (never longer than 6 hours)
    ext.ok("ext_lock")
    ext.ok("ext_unlock", {"profileId": profile, "password": EXT_PASSWORD})
    lasts_ms = ext.state()["unlocked"]["expiresAt"] - time.time() * 1000
    assert 1.9 * 3_600_000 < lasts_ms <= 2 * 3_600_000

    # the saved generator options apply to the next password
    for _ in range(10):
        assert re.fullmatch(r"[A-Za-z]{32}", ext.ok("ext_generate", {})["password"])
    custom = ext.ok("ext_generate", {"length": 12, "digits": True, "symbols": False})["password"]
    assert re.fullmatch(r"[A-Za-z0-9]{12}", custom)

    # nothing ticked at all falls back rather than failing
    nothing = ext.ok(
        "ext_generate",
        {"length": 16, "upper": False, "lower": False, "digits": False, "symbols": False},
    )["password"]
    assert len(nothing) == 16


def test_the_never_list_can_be_seen_and_cleared_and_removing_a_site_offers_saving_again(
    browser: BrowserContext, vault: SeededVault, ext: Ext
) -> None:
    origin = f"http://127.0.0.1:{vault.port}"
    ext.control.evaluate(
        "(origin) => chrome.storage.local.set({ never_save: [origin, 'https://b.example'] })",
        origin,
    )
    assert ext.state()["neverSave"] == [origin, "https://b.example"]

    page = open_login_page(browser, vault.url("login.html"))
    submit_login(page, "someone@example.com", "a fresh password for the never test")
    assert no_extension_frame(page, "prompt.html"), "a site on the list is never offered"

    ext.ok("ext_never_remove", {"origin": origin})
    assert ext.state()["neverSave"] == ["https://b.example"]
    again = open_login_page(browser, vault.url("login.html"))
    submit_login(again, "someone@example.com", "a fresh password for the never test")
    assert prompt_frame(again)  # offered again

    ext.ok("ext_never_clear")
    assert ext.state()["neverSave"] == []
    ext.ok("ext_set_offer", {"value": False})
    assert ext.state()["offerToSave"] is False
    ext.ok("ext_set_offer", {"value": True})
    assert ext.state()["offerToSave"] is True


def test_a_web_page_cannot_reach_the_management_requests(
    browser: BrowserContext, ext: Ext, page_server: str
) -> None:
    """The management requests are accepted from the extension's own pages only: a
    web page (or its content script world) gets "bad_request", and nothing changes."""
    ext.create_profile("Personal")
    ext.add_login(title="Safe")
    page = open_login_page(browser, f"{page_server}/login.html")
    for type_ in (
        "ext_import_csv",
        "ext_bin_empty",
        "ext_change_password",
        "ext_never_clear",
        "ext_report",
    ):
        reply = page.evaluate(
            "async (type) => { try { return await chrome.runtime.sendMessage({ type, args: {} }); }"
            " catch (error) { return { ok: false, error: { code: 'unreachable' } }; } }",
            type_,
        )
        assert reply is None or reply.get("ok") is False, type_
    assert _titles(ext) == ["Safe"]
