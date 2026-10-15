# Kinic Superpowers

This fork retains Superpowers' development method while making existing Kinic
Wiki file nodes authoritative for design, plan, progress, review and completion.
One saved connection supports multiple cases, with selection scoped to each
Codex chat. Source editing, test execution and Git operations run locally.

## Prerequisites and setup

- Python 3.9+ and an installed, authenticated `kinic-vfs-cli` supporting
  `read-node --json` and `write-node --expected-etag --json`.
- Select the intended database and a dedicated scope through inventory. The
  example `/Knowledge/projects/example` is illustrative, not a discovered scope.
- Set `KINIC_SUPERPOWERS_ROOT` to this fork's absolute directory, and
  run the adapter from the application checkout. No credentials go in config.
- Follow [Codex installation and hook trust](codex.md) to install this fork as
  `kinic-superpowers`. The SessionStart hook supplies the installed adapter path,
  current checkout and actual chat ID automatically.

Initialize once:

```bash
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" init --database-id DB --scope /Knowledge/projects/example
```

If necessary, provide `--cli /absolute/path/to/kinic-vfs-cli` and a human-authorized
`--allow-non-ii-identity` at initialization. The adapter saves the CLI location,
endpoint and exact principal in Git-ignored `.kinic-superpowers.json`. Explicit
CLI paths and relative PATH entries are resolved to an absolute path before
saving, so they remain usable from another checkout. The adapter checks the
active principal on access and stops on mismatch without switching identity.
Initialization verifies access; workflow creation below creates pages.

Worktrees discover the main checkout's connection automatically. Working copies,
baselines, initialization journals and chat bindings stay in each checkout's
ignored `.superpowers/` directory. Do not copy these directories between worktrees.

## Commands

```bash
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" workflow new --title "Example feature"
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" workflow list
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" --session CHAT_ID workflow use WORKFLOW_ID
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" --session CHAT_ID status
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" --session CHAT_ID check spec
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" --session CHAT_ID pull spec
# Edit the configured local working copy after reading it.
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" --session CHAT_ID push spec
```

Use the actual chat ID from the hook, never an invented or latest-session ID.
Automation can use `--workflow WORKFLOW_ID` instead. A selected chat cannot use
a conflicting explicit ID until `workflow use` intentionally changes its binding.
Missing selection is an error. `workflow list` reads wiki manifests, including
incomplete cases. `workflow new` creates a UUID scope, five pages and a manifest;
normal operations only accept a ready manifest. A failure reports a recovery
command, `workflow new --resume WORKFLOW_ID`. Retry preserves owned pages and
refuses foreign collisions. The local journal is saved before remote creation;
keep it until initialization has finished.

`status` reports local baselines and dirty copies; it does not check the remote.
Version 2 artifact results also include `workflow_id` and `workflow_title`, so
the selected case can be checked without interpreting a document path.
Successful `pull` and `push` commands also cache the verified manifest, allowing
later local `status` with an explicit `--workflow ID` and no chat binding.
`check ROLE` reads the remote and compares its revision to the baseline and
local file without updating any document or snapshot. Omit ROLE to check all
configured artifacts. Each JSON record has a `state`: `clean`, `local_changed`,
`remote_changed`, `conflict` (both changed), `untracked` (no baseline) or
`missing_local`. A failed role emits `state: error`, `remote_checked: false`
and an error message; other requested roles are still checked. Exit 0 means all
requested artifacts are clean; exit 1 means changes, missing state or a read failure. A read failure is an error, never
evidence of freshness. This is the preferred first check when inspecting a
working copy without changing it; pull is still needed to refresh stale content.
`pull` reads the current remote node and records its etag and content hash under
`.superpowers/kinic/`. It refuses to overwrite an existing file without a baseline
or with unpublished changes. Existing user documents must be preserved elsewhere
and reconciled with the wiki before becoming bridge-managed working copies.

`push` uploads a frozen copy, keeps the original node metadata, and passes the
etag from the last successful pull/push to Kinic. A failed update does not advance
the local baseline. A timeout or malformed acknowledgement can mean a write
succeeded remotely: inspect the remote, preserve the local edit, and reconcile;
do not silently retry using a freshly fetched etag.
An unchanged `push` reads the remote etag instead of writing and fails if it
differs from the baseline; it is not a silent local success.

The original version 1 [configuration example](../../kinic-workflow.example.json)
and command arguments remain supported as a single workflow. Version 1 users
still provide any required CLI/identity flags. Explicit migration uses
`init --database-id DB --scope /Knowledge/projects/example --migrate` and the
appropriate CLI/identity flags. It keeps a Git-ignored `.v1-backup`, registers
the existing five mappings in a new manifest, and leaves their contents and
etags unchanged. Select the returned/imported workflow before normal v2 use.

Each invocation writes one artifact. There is no atomic transaction across
documents. Stop on the first failed command and report the pending handoff.
Source validation and progress updates are also separate: another writer can
change a source between them. This pilot assumes one workflow controller; it
does not enforce a transaction spanning approvals and execution.
Snapshots are local working-copy metadata, never the authoritative project record.
One executor owns each working directory; separate agents/worktrees must have
their own copies. Remote etags prevent lost updates, but do not claim a task or
prevent two agents doing duplicate implementation work.

## Workflow

The protocol is in
[`kinic-workflow.md`](../../skills/using-superpowers/references/kinic-workflow.md).
The integration sections in the upstream skills take precedence over their
default local storage instructions when a configuration exists. Without a
configuration this fork does not start a Kinic workflow.

Approvals are recorded with the exact remote spec/plan revision and human
authorization evidence in progress. Review records identify the spec and plan
revisions plus the Git commit reviewed. This version does not authenticate an
approver or automatically invalidate approvals: agents must compare revisions
at resume/review and obtain renewed approval whenever a spec/plan etag changes.

Keep code and executable tests in Git/local or CI. Record commands, exit status,
commit IDs and durable evidence links in progress/review; do not treat pasted
text as proof that a command ran. Attach or upload required evidence before
deleting any local scratch file. No completion follows a failed wiki write.

## Verification and limits

```bash
python3 -m unittest discover -s tests/kinic -v
```

These tests use a fake CLI transport. They cover version-bound writes, conflict
handling, preserving dirty copies, metadata and resume in a fresh workspace
object. On 2026-10-15 a live round-trip check passed against `db_ceifht7sc2lh`
using the human-authorized `llm-wiki-mainnet` identity. Five synthetic pages were
created under `/Knowledge/kinic-superpowers/live-check-d5c15c8572e24a189d40939ea15a4e7e`.
All five were read, updated and recovered from an independent working copy;
a stale progress update was rejected and the winning content was reread intact.
See `live-check-2026-10-15.json` for artifact revisions and checks.

The CLI reports a Candid error-code decoding failure for `EtagConflict`; the
server rejection and preserved winning content were verified independently.
The adapter stops on this failure. The sibling CLI has now been repaired and
rebuilt; repeating the live stale write displays the server's readable reason.
See `cli-error-fix-2026-10-15.md` for the fix and focused Rust checks. The original
live-check report retains its original diagnostic as historical evidence.
An earlier attempt failed before page creation because the parent folder did
not exist. Bootstrap now creates the unique run folder first.

The opt-in reproduction command (creates and retains five new synthetic pages;
the parent `/Knowledge/kinic-superpowers` must already exist) is:

```bash
python3 scripts/kinic-live-check.py --database-id DATABASE_ID --cli /absolute/path/to/kinic-vfs-cli --allow-non-ii-identity --create-test-pages
```

The identity flag is only appropriate with human authorization. This is a live
adapter test, not proof of an installed agent executing the whole workflow.
Offline agent scenarios are documented separately in `evaluation.md`.

A subsequent real feature task completed design/plan approval, TDD implementation,
fresh-agent usability trials, independent review/fix/re-review, wiki completion,
and fresh-session recovery. See [full workflow report](e2e-workflow-2026-10-15.md).
This used explicitly loaded skills. Subsequent installed-plugin session and
multi-workflow validation is recorded in
[onboarding validation](onboarding-2026-10-15.md).

Future work: atomic provisioning, task ownership/dependencies, machine-checked
approval invalidation, portable attachment storage, and automated scenario evals.
