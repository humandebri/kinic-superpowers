# Codex onboarding validation — 2026-10-15

The saved-connection and multi-workflow implementation passed 73 Python tests,
seven live-database checks, independent code review, and real installed-plugin
Codex CLI sessions. Initialization provisions the connection once; a normal chat
can then create its five documents, select a case and recover its state without
constructing paths or repeating connection flags.
The local-marketplace manifest check and the retained shell SessionStart output
suite also pass. Public archive packaging was not validated for this fork.

## Installed-plugin acceptance

The actual local marketplace and plugin were installed using:

```bash
codex plugin marketplace add /Volumes/KINGSTON/KINIC/kinic-superpowers --json
codex plugin add kinic-superpowers@kinic-superpowers-local --json
```

The normal interactive hook review was opened and the SessionStart definition
was explicitly trusted. Hook trust was not bypassed and existing hooks were not
overwritten. After fixes the installed copy was refreshed; the JSON evidence
records matching source hashes for the adapter, runtime and hooks.

These were native Codex CLI sessions (`0.162.0-alpha.17.2`), not subagents or
standalone hook invocations. No test prompt named a skill. The desktop app UI
was not separately exercised; the CLI results do not establish desktop-specific
discovery or restart behavior.

| Session | Task and observed behavior |
| --- | --- |
| `01a13dd6-e20d-7de3-b8fc-7d49417c0755` | A new session asked to resume 起動確認 A. SessionStart supplied the installed command. The agent loaded the bootstrap/protocol, listed workflows, selected A, checked and pulled documents, and reported Design with no approvals. |
| `01a13dd9-e3cc-71d3-9fde-2681296b1e50` | Another new session asked to design a TODO tool in 起動確認 B. It selected B, automatically loaded brainstorming, read spec/progress and asked the first requirements question without editing code or wiki. |
| A resumed | After B had been selected in the other session, A still resolved to A. Wiki revisions were checked and fetched again. |
| A after `/compact` | The native TUI completed compaction at `2026-10-15T04:39:55.040Z`. The persisted transcript contains fresh SessionStart context bound to A after compaction. A subsequent normal prompt again checked A and read its documents. |
| `01a13ddc-064f-7270-ad12-ed3761ad57ab` | The exact clean-session prompt `Let's make a react todo list` triggered bootstrap and brainstorming, listed workflows and asked which case to use. It did not select the newest case. A subsequent request to create a new React todo list case automatically provisioned all five pages, bound it to the chat and asked a design question. |

The checked-in [native-session evidence](onboarding-2026-10-15.json) contains
prompts, commands, exit statuses, final responses and executable hashes. Full
local JSONL traces remain in ignored `.superpowers/onboarding/`; the native
rollout for A remains in Codex session storage. `check` initially returning 1
for untracked copies is expected; subsequent pulls establish their baselines.

## Usability loop and fixes

Instruction evaluation first found missing session-selection guidance, manual
page setup and an overly broad trigger. After fixing those, pressure evaluation
found an installed-path fallback error and ambiguous binding inspection. The
same scenarios passed after correction. See the detailed
[instruction evaluation](instruction-evaluation-2026-10-15.md), including its
limits. The installed sessions above then exercised those instructions through
the real harness.

The real A session reported that `status` lacked a case name, requiring UUID and
document-content comparisons. A regression assertion failed first; the adapter
was then changed to include `workflow_id` and `workflow_title` in v2 artifact
results. All 73 tests passed and the installed copy was refreshed. Repeating the
same state-inspection task after actual compaction confirmed the name/ID display
and retained A selection. Legacy output remains compatible.

Remaining usability feedback: one JSON record per document is verbose, and
`status` needs a separate `check` to establish remote freshness. The latter is
the intended local-versus-remote contract; a concise presentation can be added
later without changing that contract.

## Recovery, compatibility and isolation

The [live report](onboarding-live-2026-10-15.md) and its
[JSON evidence](onboarding-live-2026-10-15.json) cover authenticated operations in
`db_ceifht7sc2lh`, below
`/Knowledge/kinic-superpowers/onboarding-20261015`, with the already authorized
`llm-wiki-mainnet` identity. Existing validation documents were retained.

The probe deliberately interrupted creation before the plan write, edited an
already-created owned spec, then resumed without losing that edit. It completed
normal pull/push, rejected a stale push from a real Git worktree without advancing
the baseline, restored from another session binding, and migrated a separate v1
configuration while retaining all five source etags. Worktrees shared connection
settings while isolating documents, etags and session bindings. A/B's ten
document etags were unchanged.

Offline regression tests additionally cover foreign-page collisions, identity
mismatch, invalid endpoint/identity settings, malformed recovery records, v1
compatibility, no implicit target selection and local-only hooks. Independent
review identified and verified fixes for recovery-record validation, state-path
containment, ignored migration settings, cache ID matching, v1 worktree command
roots and required saved endpoints. The final read-only re-review found no
remaining material issue.

## Boundaries

No public directory distribution, GitHub publication or deployment was performed.
Server-enforced approval, task claiming and multi-document transactions remain
outside this version. Each wiki write still uses its own etag; approval evidence
and current state are recorded separately from immutable spec/plan content.
