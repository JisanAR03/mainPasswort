# M0-03 spike report: browser bridge hello world (extension → host → Qt socket)

Date: 2026-10-15 · Machine: Windows 11 · PySide6 6.12, PyInstaller (spike-only)

**Verdict: the loop works end to end locally, and the startup-time assumption is confirmed —
but only with `--onedir` packaging.** ADR-004 confirmed (no revision needed).

## What was built (thrown away after this spike)

Spike dir: `C:\Users\murad\AppData\Local\Temp\claude\pv-spikes\browser-spike\`

- `extension/` — hello-world MV3 extension (popup + service worker) with a fixed ID
  `ojbcncdjhhonhkngjfkcgobggdmceaaj` pinned via a generated manifest `key` (spike-only keypair).
- `pm_host.py` — native messaging host: reads the browser's 4-byte length-prefixed JSON from
  stdin, forwards to the app over a QLocalSocket, frames the reply back on stdout (stdout is
  reserved for the protocol; errors go to stderr).
- `server.py` — the app side: a QLocalServer (`personalvault-spike-bridge`) that echoes the
  message back.
- `fake_browser.py` — a fake browser that spawns the host as a subprocess and speaks real
  native framing: correctness round trip + 20 spawn timings.
- `install_host.ps1` — registers `com.personalvault.spike` in HKCU for Chrome and Brave
  (already run).

## Verified locally (no browser needed)

| Check | Result |
| --- | --- |
| Framing + relay + socket loop | `{'id': 'spike-1', 'ok': True, 'echo': 'hello from fake browser'}` — full round trip, clean reply. |
| Host startup, 20 popup-open proxies — venv python | min 307 / **median 345** / max 412 ms |
| Host startup, 20 popup-open proxies — PyInstaller `--onefile` | min 1549 / **median 1667** / max 2201 ms ❌ |
| Host startup, 20 popup-open proxies — PyInstaller `--onedir` | min 273 / **median 291** / max 329 ms ✅ |

## Findings that change the code plan

1. **The spec's "popup feels instant" assumption holds only with `--onedir`.**
   The onefile self-extraction costs ~1.4 s on every launch, which fails the assumption.
   The onedir build starts in ~290 ms. **M3-04's `install_native_host.py` must build and
   install the onedir layout**, not onefile.
2. **The 290 ms is paid once per browser session** — Chrome keeps the host process alive for
   the lifetime of the port, so subsequent messages are already-imported fast. The popup
   only waits on the first open.
3. **The host should not import more of PySide6 than QtCore/QtNetwork** (as in this spike):
   import time is the second-biggest cost after process start.
4. **PyInstaller must run inside the project venv** (`uv pip install pyinstaller`), not via
   `uvx` — the isolated `uvx` environment does not see PySide6 and silently produces an exe
   without Qt. (Spike-only tool; not added to `pyproject.toml`.)
5. Windows Defender's first-run scan adds ~100–300 ms to the first launch of a fresh exe;
   subsequent launches are unaffected. Expect the same in M3.

## Owner steps (close the remaining "Done when" item)

The socket + host loop is verified locally above; the spec additionally asks the owner to run
the round trip in real browsers:

1. Start the app side in a terminal (leave it running):
   `D:\PasswordManager\.venv\Scripts\python.exe C:\Users\murad\AppData\Local\Temp\claude\pv-spikes\browser-spike\server.py`
   (it prints `READY`).
2. In **Chrome**: open `chrome://extensions` → enable Developer mode → **Load unpacked** →
   pick the `extension` folder from the spike dir. Fully restart Chrome once first (it caches
   native-host registrations).
3. Click the extension icon → **Ping the app** → expect
   `{"ok": true, "reply": {"id": "…", "ok": true, "echo": "hello from extension"}}`.
4. Repeat in **Brave** (`brave://extensions`, same folder).
5. Stop the server (Ctrl+C in its terminal). Record your result (e.g. a line in this file's
   owner-check section or a note to Claude).

Expected failure modes and fixes: "Specified native messaging host not found" → registry not
seen yet, restart the browser; "host disconnected" → the server isn't running (step 1);
popup error → check the extension's `chrome://extensions` errors view.

## Uninstall (after the spike)

```powershell
Remove-Item 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.personalvault.spike'
Remove-Item 'HKCU:\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.personalvault.spike'
```

Then delete the spike folder. The keypair is spike-only and is not reused by the real
extension.
