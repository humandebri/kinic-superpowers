# Shared CLI settings and scope migration validation

Date: 2026-10-16. Branch: `feat/shared-cli-settings`. Implementation: `92f054b`,
`db4d168`, `d0041d2`, `8204b22`. No push, PR, merge, learning plugin setup or
canister upgrade was performed.

## Installed CLI and plugin

Kinic Wiki CLI was built from merged PR147 commit
`023bfb427f28c8e00dfc31642cdc8d5bf9ad2efe`, installed as
`~/.cargo/bin/kinic-vfs-cli` (version 2.0.2), SHA256
`0328bb5e12c82fb1f2275e20a43cccb2418f23117a3cf3ab0fd709d2bfe2a2f7`.
The previous executable is retained in the local ignored
`.superpowers/shared-cli/kinic-vfs-cli.before-pr147`.
The existing kinic-wiki working-tree changes were preserved; no CLI source edit
or new kinic-wiki commit was needed.

The local `kinic-superpowers@kinic-superpowers-local` plugin was reinstalled
from this source through `codex plugin add`. SessionStart remains local-only.
The ordinary persisted plugin trust configuration was used.

## Configuration and Wiki migration

Both repositories now use config v3 with native `.kinic/config.toml` connection
resolution. Each previous config is retained beside it as
`.kinic-superpowers.json.v2-backup`; the older Superpowers v1 backup remains.
Backups contain settings only, not private keys or tokens.

| Project | New entry | Files copied | Cases |
|---|---|---:|---:|
| kinic-superpowers | `/Knowledge/kinic-superpowers/index.md` | 16 | 3 |
| kinic-wiki | `/Knowledge/kinic-wiki/index.md` | 14 | 2 |

The old entries under `/Knowledge/projects/` redirect to the new entries.
Source evidence, historical approvals, fixed project IDs, case UUIDs and titles
were retained. Unrelated historical destination data was preserved. Each
repository retains its complete migration journal in
`.superpowers/kinic-project/scope-migration.json`, including original content,
etags, copy readbacks and local-state mappings. Two unrelated old Testing local
records were deliberately skipped. Four linked kinic-wiki worktrees were
inspected; none held separate selected-case state requiring migration.

## Verification

- Native CLI: 56 tests passed (agent config 9, entrypoints 14, status 21, core
  connection 12); release build succeeded.
- Adapter: 178 Python tests passed, including upstream skill comparison,
  config priority/conflicts, legacy compatibility, identity/endpoint drift,
  interrupted migration retries, two-session/worktree isolation, dirty/stale
  baselines, and read-only inspection/diagnostics. SessionStart shell checks
  passed (13 assertions).
- Live v3 endpoint drift was rejected. Doctor left all 31 inspected fixture
  files byte-identical. Native identity/access diagnostics remained `unknown`
  where credentials could not be inspected; optional learning capabilities
  did not block actual authenticated document operations.
- Live legacy and v3 transports saved and restored authored documents, rejected
  stale writes, retained dirty local copies, and preserved the winning remote
  content. Own Testing fixtures were deleted conditionally by captured etag,
  followed by an empty-prefix readback.
- Native installed-plugin chats below used natural language without DB/path
  arguments or skill names. They registered a case without placeholder pages,
  selected it in a fresh chat, and fetched its authored plan/current state.
  No redundant authorization was requested.

| Trial | Native Codex thread |
|---|---|
| New case | `01a142cf-d475-7ca1-b8d5-8dad1e1dbf64` |
| Select existing case | `01a142d2-8994-7521-ac07-ba41e46e0aec` |
| Fetch saved plan/current state | `01a142d4-17f3-7763-bcc7-240604a945c7` |

These were real `codex exec` chats using the installed plugin, not a standalone
hook invocation or subagent simulation. Desktop UI interaction itself was not
tested. The test harness initially caught the wrong Python exception type for
v3 transport; the expected server etag rejection was confirmed and the harness
resumed against preserved state.

Task reviews caught and fixed legacy doctor incorrectly requiring shared
settings and migration inspection creating a lock file. Final cross-feature
review found no additional actionable defects.

## Operational limits

Migration uses conditional writes, not a cross-document transaction; other
writers must remain quiescent. A completed journal supports idempotent replay of
that migration, not a different migration. Diagnostics report unknown honestly;
successful document access is separate evidence, not a fabricated diagnostic
permission result. The existing dedicated checkout and local branch are retained.
