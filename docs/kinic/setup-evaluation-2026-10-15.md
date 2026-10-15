# Setup instruction evaluation (2026-10-15)

This is a static instruction evaluation by a fresh evaluator, not an installed
Codex session, CLI execution, live database test, or desktop acceptance result.
The evaluator read the setup documentation, skills, CLI parser and initialization
implementation. No CLI/network operations were performed for this evaluation.

## Baseline

Scenario: an unconfigured application repository; the user asks Codex to handle
database and path selection through the CLI. The CLI is on PATH and supports
database current/list. The conversation already authorizes `llm-wiki-mainnet`
and explicitly selects `db_ceifht7sc2lh`.

The original `using-superpowers` skill stopped at the missing configuration.
The setup documentation required the user to choose a scope and provide a DB
ID. The parser required both `--database-id` and `--scope`. There was no setup
skill or discovery procedure to bridge that gap.

## Revised scenarios

| Scenario | Expected behavior supported by the revised files |
| --- | --- |
| Original setup request | `setup-kinic` applies before configuration. Run `init --inspect`, reuse prior authorization/eligible DB choice, then initialize without requiring the user to build a scope or command. |
| CLI-linked database | Reuse the linked DB, verify access, expose its name during inspection, and generate the project scope. |
| Exactly one writable database | Choose the sole active owner/writer candidate; exclude deleted or cycles-suspended candidates. |
| Multiple writable databases | Reuse a previously explicitly selected candidate; otherwise ask by name and retain IDs internally. Do not choose by recency. |
| Existing v2 configuration | Preserve database, scope, CLI and principal. Reject retargeting or an identity mismatch; reuse the existing scope after repository relocation. |
| Existing v1 configuration | Inspection identifies migration as required. Preserve the configuration unless migration is explicitly requested. |
| Non-II identity without authorization | Ask about the current identity once. Do not silently authorize or switch it. Prior human authorization can be reused for inspection and initialization. |
| Unrelated development request | Do not initialize an unconfigured repository. The setup skill requires an explicit setup request. |
| No writable candidates | Report the access issue; do not create a database or invent a local fallback. |

Static retest passes for these instruction scenarios. `init --inspect` reaches
neither configuration saves nor page creation. Both init selection flags are
optional. Setup alone creates no workflow or approval. The documentation now
describes chat-driven setup and the inspect/init procedure rather than requiring
manual DB IDs and paths.

The first revised pass exposed two gaps: selected/linked databases had no display
name in inspection output, and older documentation still required manual flags.
The final pass confirms `database_name` lookup and updated documentation, plus
the explicit setup cross-reference in `using-superpowers`.

## Limits

This evaluation does not establish automatic skill discovery in a real installed
Codex session; that requires separate session evidence. It also does not execute
the identity, access, candidate filtering or filesystem branches. Linked/saved
databases are reused based on existing connection choice and access checks;
the writable-role filter is specifically applied when choosing from an unlinked
inventory. Databases without a returned name can still yield a null display
name, so agents must not invent one.

The later setup review fixed the linked/saved write-access gap described above:
initialization and inspection now require an active, unsuspended owner/writer
entry for the selected DB. They stop without changing configuration if access
is read-only or revoked. Another regression uses a real Git worktree to verify
that first initialization saves shared settings in the main checkout, keeps
document/session state local and leaves inspection read-only. All 87 Python
tests pass. Read-only inspection of the configured Memo database also succeeded
without changing the saved configuration.

## Separate native CLI verification

After the static evaluation, the root agent tested a real installed-plugin
Codex CLI session, `01a13def-99f5-7fa1-a8af-58511b35ee86`, in an unconfigured
disposable Git repository. A natural setup request automatically loaded
`setup-kinic`, inspected the CLI and presented Memo and Dom's Brain by name.
The follow-up "Memo を使って設定して。保存先はおまかせ。案件はまだ作らないで。"
saved a v2 connection with a generated scope. No skill name, database ID or
scope was supplied by the human-facing prompt; no workflow was created.
Commands, exit statuses and final responses are recorded in
[native setup evidence](setup-live-2026-10-15.json). All 84 Python tests passed.
The calling kinic-wiki checkout was also configured against the user's previously
selected Memo database and authorized identity; its connection settings remain
Git-ignored. Desktop UI behavior was not separately tested.
