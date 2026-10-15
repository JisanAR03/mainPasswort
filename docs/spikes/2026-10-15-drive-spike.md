# M0-04 spike report: Google Drive round trip (blocked on the owner's account)

Date: 2026-10-15 · Status: **skeleton ready; the run itself is an owner step**

The spec's M0-04 requires a throwaway Google account and an OAuth client, which only the
owner can create. Everything that does not need the account is built: the spike script and
the setup guide. The spec's "Done when" item "A file round-trips through Drive, and its
revision list is readable" stays open until the owner's day-1 run.

## What is ready

- **Setup guide:** [docs/setup-google-drive.md](../setup-google-drive.md) — throwaway
  account, project, Drive API, consent screen In production, Desktop-app OAuth client,
  where to put `client_secret.json`, the day-1 run, and the 8-day token test.
- **Spike script:** `C:\Users\murad\AppData\Local\Temp\claude\pv-spikes\drive-spike\drive_spike.py`
  (thrown-away code, outside the repo). Uses only the project's real dependencies
  (`google-auth`, `google-auth-oauthlib`, `requests` — no google-api-python-client), so it
  also validates the chosen dependency set for M5. It checks, in order:
  1. upload with `appProperties` → `version == 1`, `md5Checksum` matches, appProperties
     round trip;
  2. content update → `version == 2`, new `md5Checksum`;
  3. the revision list is readable and has ≥ 2 revisions;
  4. the `appProperties has {…}` search finds exactly the one file (the ADR-010 search);
  5. median upload+download round-trip time over 5 cycles;
  6. deletes the test file, keeps `token.json` for the day-8 test.
- **Token survival check built in:** the day-8 re-run must print
  `PASS token.json reused (no browser)`. A fresh browser prompt instead means the consent
  screen is still in Testing (refresh tokens die after 7 days) — the guide explains the fix.

## Owner steps

1. Follow [docs/setup-google-drive.md](../setup-google-drive.md) — create the throwaway
   account and the OAuth client, put the downloaded JSON at
   `C:\Users\murad\AppData\Local\Temp\claude\pv-spikes\drive-spike\client_secret.json`.
   **Start today: the 8-day test clock runs from the first run.**
2. Run the day-1 spike (command in the guide) and paste the PASS/FAIL lines back here.
3. Run the same command again after 8 days and confirm
   `PASS token.json reused (no browser)`.

Until the day-1 run reports PASS on the revision check, ADR-004 is confirmed in design
only (see the ADR index).

## Notes carried into M5

- **Gap #4 stands:** `drive.file` is per OAuth client, so every device uses this same
  `client_secret.json` (kept local-only, git-ignored). M5 must ship it the same way.
- The spike talks raw REST with `requests`, so M5's sync client needs no extra dependency.
- The token file lives outside the repo, like the client secret; in the real app the
  refresh token lives inside the vault (ADR-004).
