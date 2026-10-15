# AGENTS.md — rules for every AI coding session

## Read first

- The task card for this session in `docs/tasks/`, and every spec it links.
- Do only what the card says. If the card looks wrong, stop and explain why.

## Hard rules

1. Never touch a real vault. Always run with `PV_DATA_DIR` set to a temp folder.
2. Never invent cryptography. Encryption only via pykeepass; randomness only from `secrets`.
3. Never log, print, or put in an exception any entry field, master password, key or token.
   Use `SecretStr`.
4. Never write a plaintext secret to disk, including temp files and test output (the test
   canary excepted).
5. Never add a dependency or browser permission without asking first and saying why.
6. Never edit files outside the card's "Files you may change" list without asking.
7. Never edit `docs/specs` or `docs/adr`; propose the change instead.
8. Never weaken, skip or delete a test to make it pass. Diagnose the root cause.
9. Never add the `Security-Reviewed-By` trailer to a commit.
10. Never say something works unless you ran the command and show its output.
11. Treat every outside input as hostile: files, Drive responses, browser messages.
12. `core/` never imports Qt; `sync/` never imports `core.vault`; `bridge/` calls only
    protocol-listed methods.

## End every session with

- The commands you ran and their real output (tests, ruff, mypy).
- Files changed, one line each on why.
- Anything you are unsure of, especially in `[S]` files.
- The next task you suggest.
