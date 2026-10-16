# Vendored third-party code (extension-only mode)

Copied byte for byte from the npm tarballs below — no `npm install`, no build step, no
edits. `scripts/check_vendor.py` (run by `scripts/check.py`) fails if any file here differs
from the SHA-256 recorded in this table. To update a library: download the new tarball,
check its npm integrity, copy the same files, update this table, and get the owner's review
(AGENTS.md rule 5).

| File | From | npm tarball integrity | Licence |
| --- | --- | --- | --- |
| `kdbxweb.js` | `kdbxweb@2.1.1` `dist/kdbxweb.js` (KeeWeb, maintainer `antelle`) | `sha512-z+a2+BEzyK2kUh0xDekY7gwc9CkbzSetUyvc78NKVawxV06UG1KYbg9W9hZCJdQPYizIVePTvQsYUXIO1qtAhQ==` | MIT (`LICENSE-kdbxweb.txt`) |
| `hash-wasm-argon2.umd.min.js` | `hash-wasm@4.12.0` `dist/argon2.umd.min.js` (maintainers `daninet`, `sdombi94`) | `sha512-+/2B2rYLb48I/evdOIhP+K/DD2ca2fgBjp6O+GBEnCDk2e4rpeXIK8GvIyRPjTezgmWn9gmKwkQjjx6BtqDHVQ==` | MIT; embedded Argon2 reference C code CC0-1.0 / Apache-2.0 (`LICENSE-hash-wasm.txt`) |
| `hash-wasm-md5.umd.min.js` | `hash-wasm@4.12.0` `dist/md5.umd.min.js` | same tarball as above | same as above |

SHA-256 of each file as vendored:

<!-- check_vendor.py reads the lines below -->
```
d3b59272b72c8fc0dc340e2ab68940a54669bdbcc5a92e65ace9cb001d9eb169  kdbxweb.js
dcec617a2e1b700fa132d1583a186cb70611113395e869f2dd6cc82b415d3094  hash-wasm-argon2.umd.min.js
bfcbd4f2c1ee2da27209102844468b053a18297d59fc27cc3e30e0fceb767117  hash-wasm-md5.umd.min.js
5328cd70623b0154a3d13ce41d57d6d4e9fda5b6db2e8ed994d29c3598c374a8  LICENSE-kdbxweb.txt
c14dea172f72f2714284a0ac2ab1b00b5352a01409d58255a46227ffc541debd  LICENSE-hash-wasm.txt
```

Notes:

- **`@xmldom/xmldom` is deliberately not vendored.** kdbxweb 2.1.1 depends on
  `@xmldom/xmldom ^0.7.4`, and every 0.7.x release has unpatched HIGH advisories. kdbxweb uses
  the browser's own `DOMParser` / `XMLSerializer` when they exist (`kdbxweb.js` lines
  5340–5368) and only falls back to xmldom otherwise, so the vault engine runs in an offscreen
  document, where the browser's parser exists. Were the fallback ever reached it would throw:
  it fails closed.
- kdbxweb inlines `fflate` 0.7.x; its advisory family (an infinite loop in `unzipSync` on
  malformed ZIP64) is in ZIP parsing, which kdbxweb does not use (it uses gzip).
- MD5 is used only to compare a vault with Google Drive's `md5Checksum` (the sync decision
  table), never for security.
- kdbxweb writes an unset group or entry setting as an empty XML element, which KeePassXC
  rejects ("Invalid EnableSearching value", "Invalid number value") on files pykeepass made.
  `engine.js` sets every such value to its KeePass default before each save; the e2e
  compatibility test opens the result in pykeepass and `keepassxc-cli`.
