# Google Drive setup (M0-04 spike, then M5 sync)

The spec requires a **throwaway Google account** for the Drive spike, with an OAuth client
of type **Desktop app**, the Drive API enabled, and the consent screen **In production**.
The same account and `client_secret.json` later serve the real M5 sync (spec issue #4:
`drive.file` is per OAuth client, so every device uses this same file).

> ⚠️ The 8-day token test runs from the day of the first spike run — **start today** if
> possible.

## 1. Create the throwaway account

Create a new Google account (any name; it is temporary and never reused for anything else).
Note its address and password somewhere private — you will need them for every test run.

## 2. Google Cloud console

Signed in **as the throwaway account**, open <https://console.cloud.google.com> and:

1. **Create a project** — name: `Personal Vault spike`.
2. **Enable the Drive API** — APIs & Services → Library → search "Google Drive API" →
   Enable.
3. **OAuth consent screen** — APIs & Services → OAuth consent screen → choose **External**:
   - App name: `Personal Vault spike`; support email: the throwaway address.
   - Audience: skip (unpublished test app). Scopes: add nothing — `drive.file` is requested
     by the app at run time and is a non-sensitive scope, so no verification is needed.
   - **Publishing status: "In production"** (this is the part the 8-day test checks: in
     "Testing", refresh tokens expire after 7 days; in production they do not).
4. **Create the OAuth client** — APIs & Services → Credentials → Create credentials →
   OAuth client ID → Application type: **Desktop app** → name: `Personal Vault spike` →
   Create → download the JSON.

## 3. Put the file where the spike expects it

Save the downloaded JSON **exactly** as:

```
C:\Users\murad\AppData\Local\Temp\claude\pv-spikes\drive-spike\client_secret.json
```

That folder is outside the repository (the repo's `.gitignore` also covers
`client_secret*.json`). Keep the file local-only; never commit or share it. (For a
Desktop-app client it is not a true secret, but there is no reason to distribute it.)

## 4. Run the spike (day 1)

```
D:\PasswordManager\.venv\Scripts\python.exe C:\Users\murad\AppData\Local\Temp\claude\pv-spikes\drive-spike\drive_spike.py
```

A browser tab opens once: sign in as the throwaway account and approve the `drive.file`
request (it only ever shows your throwaway address). Then expect PASS lines for: upload,
version 1, md5Checksum, appProperties round trip, version 2 after update, ≥ 2 revisions,
and the appProperties search, plus a timing line and "Done." The script writes
`token.json` next to itself (local-only, like the client secret).

## 5. Run it again after 8 days (the token test)

Run the **same command** at least 8 days after the first run. It must print
`PASS token.json reused (no browser)` — proof the refresh token survived past Google's
7-day "Testing" limit, i.e. the consent screen really is in production.

If instead it opens the browser again (`browser auth used`), the consent screen is still in
Testing: set it In production (step 3 above), then re-run and restart the 8-day clock from
that day.

## 6. Keep for M5

Keep the throwaway account, the client secret and the token: M5 uses the same account and
client for the real sync spike and the G4 gate. If the account is ever compromised, it only
ever held encrypted vault files with `drive.file` scope, plus this test data.

---

# Using sync in the app

Everything above produced the throwaway account and `client_secret.json`. What follows is what
the owner does in the app, and what each line it prints means.

## 7. Give the app the client file

The app looks for `<data folder>/client_secret.json` — on Windows
`C:\Users\<you>\AppData\Local\PersonalVault\client_secret.json`. You never copy it by hand: the
first time you click **Link Google Drive**, the app asks for the JSON you downloaded and puts a
copy there (that folder is outside the repository, and the name is git-ignored). One file
serves every profile and every device — `drive.file` access belongs to the OAuth client, so the
same file is what makes each device see the same vaults.

## 8. Link a profile

1. Unlock the profile. The line at the top says **Sync off** and offers **Link Google Drive**.
2. Click it. The first time, choose your `client_secret.json`; then a browser tab opens. Sign in
   as the throwaway account and approve the `drive.file` request. That tab is the only thing
   that ever sees your Google password — the app never does.
3. The app stores the refresh token **inside the vault**, in the hidden `.app` group as the
   `drive-sync` entry, so it is locked with everything else, and syncing starts: the line goes
   **Waiting to upload**, then **Synced**.

What lands in Drive is `My Drive/PersonalVault/<profile id>/vault.kdbx`. It is found by an
`appProperties` marker, never by name, so renaming or moving it does not break sync. Drive only
receives the encrypted file, and only bytes that were verified by decrypting them first (I10).

Uploads wait out the **upload quiet period** (Settings, 10 s by default) after a save, so a
burst of edits is one upload. A full sync also runs every **sync interval** minutes (Settings,
60 by default), on unlock, when the network comes back, and on **Sync now**.

## 9. A second device

Install the app, copy the same `client_secret.json`, and sign in with the same throwaway
account. Two cases:

- **The profile is new there:** sync uploads its vault and the line goes **Synced**.
- **Drive already has a vault for that profile** (you copied the profile folder across, or you
  are re-creating it after a reinstall): the app decides nothing. The line says **Needs
  attention** and offers **Use Drive's copy** or **Keep this vault**. Whichever you choose, the
  losing copy is still kept — locally in `backups/`, and in Drive's revision history. This is
  the ADR-010 rule: a sync never overwrites a copy it has not seen.

## 10. What the status line means

| Line | What it means | What to do |
| --- | --- | --- |
| **Synced** | This device and Drive hold the same file. | Nothing. |
| **Waiting to upload** | A change here is newer than Drive's copy and the upload is queued. | Nothing, or **Sync now**. |
| **Offline** — retrying at HH:MM | Drive could not be reached. Retries go 30 s, 1, 2, 4, 8, 16, 30 minutes apart, then every 30 minutes; a success resets that. | Nothing: it catches up by itself. |
| **Conflict** | Both copies changed since the last sync, and nothing has been uploaded, adopted or deleted. | The banner's three choices (below). |
| **Reconnect Google** | Google no longer accepts this profile's sign-in (revoked, expired, or the scope changed). | **Unlink**, then **Link Google Drive** again. |
| **Sync off** | This profile is not linked: never linked, unlinked, or the vault is locked. | **Link Google Drive**, or unlock. |
| **Needs attention** | Something only you can decide — usually the first link above, or Drive's file is missing or in the bin. | Read the line; if it is in the bin, restore it in Drive and press **Sync now**. |

**Unlink** forgets the sign-in: the token entry is deleted from the vault and syncing stops.
The vault, its backups and the file in Drive are untouched. To make Google forget the app as
well, remove its access at <https://myaccount.google.com/permissions>.

## 11. A conflict, and the three choices

A conflict is not an error: it means this device and another one both saved changes between two
syncs, and the app refused to guess which is right. The line says **Conflict** and a banner
appears above the list:

- **Keep mine** — this device's vault goes to Drive. Drive's copy is kept in
  `<profile folder>/sync/conflicts/` and in Drive's revision history, so nothing is lost.
- **Take theirs** — Drive's copy becomes this device's vault. Your file is backed up to
  `backups/` first, then their copy is uploaded, so Drive and this device agree again.
- **Open both** — Drive's copy opens read-only in a window beside your vault, with the same
  guarded clipboard, so entries can be carried across by hand before you choose.

Nothing happens until you click one of them. M6 adds entry-level merge, which replaces
**Open both** for the everyday case of two devices editing different entries.

## 12. What sync does not do yet

- It moves whole files: two devices editing *different* entries still meet a conflict (M6).
- It never touches anything in your Drive except the `drive.file` files it created.
- It does not sync while the vault is locked: the master password is what verifies every upload
  and every adoption.
- Deleting the vault file in Drive stops that profile's sync and asks; it is never silently
  re-created.
