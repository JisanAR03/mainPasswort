# ADR-009 Where the Security-Reviewed-By trailer lives

Status: Accepted
Date: 2026-10-15

## Context
CI runs on the pull request's commits, before the squash commit message exists, so the
`sensitive-review` job cannot see a `Security-Reviewed-By:` trailer that is added only at
merge time. The owner asked for the simplest reasonable resolution.

## Decision
The review sign-off must appear in a place CI can check and history preserves:

1. The owner adds `Security-Reviewed-By: <name>` to the pull request **body** after reading
   the diff of every `[S]` file (a commit message inside the PR also satisfies the check).
2. The `sensitive-review` CI job fails if the PR changes an `[S]` file and neither the PR
   body nor any commit message carries the trailer.
3. At merge time, the owner pastes the same trailer into the squash-merge commit message,
   so the sign-off survives in `main`'s history. The gate sign-offs (G2, G5) re-check this
   by hand.

## Consequences
CI enforcement works with squash merges; the trailer survives the squash. The owner, not
the AI, always adds the trailer (AGENTS.md hard rule 9).
