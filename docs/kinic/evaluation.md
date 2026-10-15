# Pilot evaluation record — 2026-10-15

Upstream baseline: `bb92a77741419a4ab5f06e711a283343f1ada0c3`.
Evaluated in Codex with a disposable subagent reading files, not an installed
plugin or a live canister. No transcripts or project data were uploaded.

## Before changes

An independent reader inspected the seven workflow skills. None described wiki
refresh, wiki write acknowledgements, revision-bound wiki approvals or etag
conflict handling. In particular executing-plans said:

> Harness todos are a live view; the ledger is the record.

and:

> after compaction, trust the ledger and `git log` over your own recollection.

Under the scenario of stale local completion versus a newer wiki plan, these
instructions provided no remote recovery step. Final cleanup explicitly treated
Git as the record and deleted the plan workspace.

## After changes: independent instruction walkthrough

The reader applied the modified instructions to each skill separately:

| Skill | Scenario | Prescribed action identified |
|---|---|---|
| using-superpowers | New session with stale local ledger | Find config, load wiki protocol, require stage pulls |
| brainstorming | Pressure to skip upload | Push spec, then record actual approval etag in progress |
| writing-plans | Source spec changed since approval | Refresh source and approval references before dependent work |
| executing-plans | Local completion differs from wiki | Pull/read progress, verify cited commits, resume remote state |
| subagent-driven-development | Etag conflict after task | Preserve changes, stop dispatch, deliberately reconcile |
| requesting-code-review | Pressure to accept local-only review | Push review and revision reference in progress |
| finishing-a-development-branch | Final wiki upload fails | Preserve workspace; completion and cleanup blocked |

The evaluation found a real worktree ambiguity: using the original checkout's
config anchors local files to the wrong root. The protocol now requires a
per-worktree config and baselines. It also now requires renewed approval on a
source etag change, eliminating discretion about whether a change is material.

The reader additionally identified unchanged-push freshness as a possible gap.
A new regression test failed against the initial implementation; unchanged push
now reads/checks the remote etag. Cross-document atomicity and task ownership
remain limitations explicitly documented in setup/protocol.

## Executable checks

`python3 -m unittest discover -s tests/kinic -v` covers 23 tests including a real
subprocess round trip against a fake CLI executable. Other cases exercise stale
etags, ambiguous acknowledgements, missing baselines, dirty-file preservation,
metadata preservation, remapped databases, path escapes, timeouts and restart.
Tests run locally and neither select a database nor invoke the actual Kinic CLI.

## Subsequent live adapter check

With human authorization, `scripts/kinic-live-check.py` exercised five synthetic
pages on `db_ceifht7sc2lh` with identity `llm-wiki-mainnet`. The stable report is
`live-check-2026-10-15.json`. It verified all five round trips and independent
working-copy recovery, stale-write rejection, preserved winning content and
dirty-copy protection. This is additional live transport evidence, not an
installed-agent run or a test of task execution/approval enforcement.

The actual server response selected `EtagConflict`; the CLI failed to deserialize
that PascalCase code. The rejected write did not advance the local baseline or
change the server's winning document. Result classification tests ensure merely
listing `EtagConflict` in a Candid type table cannot falsely pass the check.

## Evidence boundary

This is an offline walkthrough and adapter contract test suite. It is not the
upstream Gauntlet evaluation harness, repeated behavioral micro-testing, an
installed-harness integration test, or a live wiki end-to-end run. Those checks
remain necessary before claiming production readiness. No task-claim/lease
service, server-enforced approvals or atomic new-node provisioning is included.

The later feature-development run is recorded in
`e2e-workflow-2026-10-15.md`; it adds real multi-agent stage execution and wiki-only
fresh-session recovery evidence, while retaining the automatic-bootstrap limit.
