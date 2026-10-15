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
