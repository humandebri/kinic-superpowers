# Wiki-backed development workflow validation

Database: `db_ceifht7sc2lh`, human-authorized identity `llm-wiki-mainnet`.
Remote workflow scope: `/Knowledge/kinic-superpowers/e2e-check-0130dbdd324c`.
The task was a real `check [ROLE]` feature, not synthetic test results written
into five documents. The human explicitly approved its specification and plan.

| Stage | Executed evidence |
|---|---|
| Design | Spec drafted in wiki; human approved behavior and scope |
| Plan | Wiki plan binds spec etag; approval evidence and exact revisions in progress |
| Implementation | Failing tests observed, then 30 Python tests passed; feature commit `6efca2b` |
| Usability | Two fresh agents attempted the same read-only freshness task; v1/v2 reports preserve their feedback |
| Review | Independent reviewer found batch fail-fast bug; regression reproduced it; correction `caa7981` passed tests and scoped re-review |
| Live verification | clean/remote_changed/conflict, no file/snapshot mutation, missing first role followed by a later result |
| Completion | Review and completion pushed to wiki, acknowledged revisions referenced by progress |
| Fresh-session recovery | New agent pulled all five roles into an independent directory, recovered approvals, completed tasks and review disposition, and verified cited Git commits |

Pinned approved source revisions:

- spec: `v4h:07ee4f97d9168f5e10a183c67857ea12d92c4e1fc58df5ba02cb073501509e01`
- plan: `v4h:400091e6480115a997807f1f935b72fb44f4b8bf9d1ff259ffdfb5b44b37f5cb`

The fresh recovery agent reported:

> Recovery succeeded using only the permitted documents and five fresh wiki pulls

It also noticed obsolete pending-approval language in pinned design/plan and
older progress events. The progress document now begins with a current-state
summary, actual approval references and an explicit historical-events boundary.
Approved source snapshots were not silently rewritten. Future workflow templates
should keep mutable stage labels out of immutable spec/plan text.

## Usability findings

- Before check existed, the baseline agent combined bridge status and direct
  Kinic CLI reads: eight shell commands including documentation inspection.
  After the change, the fresh agent used two inspection shell commands and one
  workflow invocation plus a poll. These are observed counts, not a latency benchmark.
- README did not identify the example config location clearly. Added direct link.
- Batch check stopped after the first read error. Now emits per-role error JSON,
  continues later roles and keeps nonzero exit status.
- CLI error names could not be decoded. The sibling patch fixes all five codes;
  two Rust tests, formatting, rebuild and live stale-write retry passed. Patch:
  `patches/cli-mutation-error-aliases.patch`. No server deployment was required.
- Provisioning five pages, carrying config into worktrees, and explicit CLI/path
  identity flags remain setup friction. No task leases or transactional approval
  enforcement are implemented.

## Limits

This was real multi-agent execution with explicitly loaded skills, real code
changes, actual test failures/successes and live wiki writes. It was not a clean
installed-plugin automatic-bootstrap acceptance test. Source/test commits and
artifacts are retained locally; no merge, deployment, public PR or release was
part of the approved task. Existing unrelated user work in kinic-wiki was preserved.

The Rust repair remains a scoped local change in the sibling kinic-wiki checkout;
its immutable patch is included here because that change has no separate commit
ID. The baseline/feature/correction Git IDs recorded in wiki belong to this fork.
The four configured spec/plan/review/completion working copies and local config
are ignored by Git in this checkout; their exact approved text and current
workflow state remain in wiki. Reports and executable evidence are tracked.
