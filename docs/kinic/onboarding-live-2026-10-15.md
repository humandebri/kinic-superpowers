# Onboarding live verification — 2026-10-15

Result: passed

Database: `db_ceifht7sc2lh`; dedicated scope: `/Knowledge/kinic-superpowers/onboarding-20261015`.

## Checks

- partial_creation_resume_preserves_owned_content: passed.
- normal_pull_push: passed.
- worktree_connection_and_state_isolation: passed.
- stale_push_rejected_baseline_preserved: passed.
- another_chat_restores_from_wiki: passed.
- legacy_migration_preserves_document_etags: passed.
- existing_workflow_documents_unchanged: passed.

## Evidence

The JSON report contains workflow IDs, fixture paths, and the stale revision error. Existing workflow document etags were compared before and after; these documents were not edited.

The partial creation failure was deliberately injected before the plan write. Real authenticated CLI calls performed all other reads and writes. The stale push used a separate Git worktree and preserved its original etag snapshot.

The disposable Git worktree remains under `.superpowers/onboarding/repo/.worktrees/live-probe` for inspection.

The separate chat check uses distinct session IDs through the Project API. It does not establish that a real new Codex chat automatically runs SessionStart or selects skills; that acceptance check is separate.
