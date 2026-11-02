# Redesign verification — 2026-10-16

Baseline: obra/superpowers `bb92a77741419a4ab5f06e711a283343f1ada0c3`.
The baseline was cloned locally and its skills, prompts and helper scripts were
read before implementation. See [contract.md](contract.md) for the allowed changes.

## Automated and reviewer evidence

The upstream body comparison covers eight development skills. All their auxiliary
prompts, reference documents and scripts are compared against the pinned Git tree,
allowing only the namespace substitution. Storage instructions use marked blocks.
The final Python suite passes 145 tests. Both upstream helper suites (`test-sdd-workspace.sh` and
`test-executing-plans-scripts.sh`) pass. Python tests cover old configurations and
manifests, lazy authored documents, interrupted publication, foreign page rejection,
identity pinning, repository collisions, isolated sessions/worktrees and migration.

Review findings fixed with regression tests:

- Restore execution copies into the helper's workspace for the current checkout,
  including a conflicting existing ledger marker.
- Revalidate manifest identity under the publication lock.
- Enforce repository registration at the public CLI boundary for new configurations.
- Resolve relative and encoded references before deleting historical test pages.
- Exclude successfully saved spec/plan working copies from Git without untracking existing files.
- Honor an unambiguous case already named by the user instead of asking again.

## Actual installed Codex plugin trials

These are native Codex CLI chats using the installed plugins and ordinary persisted
hook trust, not subagent simulations. The temporary upstream validation plugin was
removed after comparison. Desktop UI operation itself was not exercised.

| Identical request | Upstream chat | Fork chat | Observed behavior |
|---|---|---|---|
| Fix only `Welcom` in README | `01a14226-e3af-72b3-b2b6-fbd1918379ab` | `01a14226-70b2-7463-b1a4-a98bcee25ba6` | Only README edited; no spec, plan or workflow placeholders |
| `Let's make a react todo list` | `01a14227-51eb-75f3-8756-e0f2839fab9f` | `01a14227-4d86-7140-a029-2e6b993a3bb3` | Both automatically used brainstorming and asked about scope before implementation |

Fresh recovery used the ordinary request to resume the named storage-validation
case, without naming a skill. The first attempt exposed an unnecessary selection
confirmation and a host sandbox limitation: the authentication CLI needs its lock
file outside the fixture. The hook wording was corrected; the retry used the
already-authorized authentication in a full-access execution environment.
Chat `01a1422c-3543-7191-8739-85cd3a983e09` selected the named case, restored both
plan and ledger, checked their identity and freshness, and correctly reported that
no implementation completion or approval had been recorded. No document was edited. The same chat was then resumed with a deliberately low
auto-compaction threshold; the native rollout recorded four compaction events.
It kept the same selected case, checked plan and ledger against Wiki again and
reported the same position without creating or editing documents.

Inline/subagent review differences were checked by source equality, helper tests
and independent instruction-trace evaluation. This does not claim two complete
native application implementations or server-enforced approval semantics.

## Live Wiki verification

The lazy-document trial used an isolated `/Testing/kinic-superpowers/` scope:
empty registration, authored plan and ledger, a second checkout restoration,
remote update detection, stale-write rejection, and preservation of both conflicting
copies all passed. The legacy transport trial also passed all five role round trips,
fresh-session restoration, stale-write rejection and dirty-copy preservation; its
synthetic namespace was deleted using captured etags and checked empty.

Substantive historical check documents were copied under the repository project,
read back and compared. Each retains its exact original path/etag as provenance;
old approvals are not approvals of the imported copy. Original substantive source
pages remain as historical evidence. Migration journals and raw session transcripts
are local ignored evidence, not knowledge pages.

Per-document CAS cannot make the reference scan and deletion a cross-document
transaction. Changed sources/destinations and new children stop cleanup. The first
cleanup attempt stopped before deletion because this run's publication had changed
the destination index. A separate journal records deliberate index revalidation;
source snapshots were not refreshed to bypass change detection.

The isolated lazy-document/native-recovery test namespace was also deleted after
its reports were captured, with an etag snapshot and an empty-inventory check.

Historical cleanup completed: all 38 snapshotted nodes were conditionally deleted
and each deletion was read back. No source snapshot was changed. The substantive
e2e originals remain intact; the project index points to the organized copies.
