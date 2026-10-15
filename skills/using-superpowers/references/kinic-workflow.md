# Kinic Wiki workflow protocol

Applies when the development project's root contains `.kinic-superpowers.json`.
Use that root even if a command runs from a nested directory. When creating a
worktree, copy the config into its root, retaining the same remote mappings and
relative local mappings. Select that worktree's config and PROJECT_ROOT; never
point its executor at the original checkout's config. Pull fresh copies there,
preserving/reconciling any preexisting mapped files first. Pass the selected
config path into subagent briefs. No config means upstream defaults.
A present but invalid config or unavailable wiki is an error, not permission to
fall back to local-only execution.

## Authority and commands

This protocol overrides the skills' default document paths, Git-only recovery,
and scratch cleanup instructions. The configured wiki nodes are authoritative;
their `local` paths are working copies needed by upstream scripts. Source code
and test execution stay in Git/local or CI. Set `KINIC_SUPERPOWERS_ROOT` to this
fork's root and `PROJECT_ROOT` to the directory containing the selected config.

```bash
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" --config "$PROJECT_ROOT/.kinic-superpowers.json" pull spec
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" --config "$PROJECT_ROOT/.kinic-superpowers.json" pull plan
python3 "$KINIC_SUPERPOWERS_ROOT/scripts/kinic-workflow.py" --config "$PROJECT_ROOT/.kinic-superpowers.json" pull progress
```

Use `push ROLE` after editing the configured working copy and require success
before handing it off. `status ROLE` reports the last known etag and dirty state;
it never proves remote freshness. Read each fetched document, not just command
output. Resolve the script path from this skill's installation; never assume it
exists in the application repository.

All five roles (`spec`, `plan`, `progress`, `review`, `completion`) must be mapped
and provisioned as existing wiki file nodes before a complete workflow. A missing
node or mapping blocks its dependent stage. The adapter intentionally does not
create or publish wiki nodes. Select the database and scope with the human;
do not guess them from examples. Never upload secrets or raw session transcripts.

## Stage contract

| Stage | Before work | Durable handoff |
|---|---|---|
| Brainstorming | Pull/read spec and progress; consult relevant knowledge | Push spec; record human approval evidence and its exact acknowledged spec etag in progress; push progress |
| Writing plans | Pull/read spec, plan, progress; check spec approval against fetched etag | Plan includes spec path+etag; push plan; record plan approval with plan etag in progress and push progress |
| Executing plans / subagent development | Pull/read spec, plan, progress on entry and resume; validate approval references | After every completed task, push progress including task ID, commit IDs, test commands/results, rulings and evidence references before dispatching the next task |
| Requesting review | Pull/read spec, plan, progress, review; check revisions and Git HEAD | Review includes spec+plan etags, BASE/HEAD SHAs, findings, dispositions and evidence; push review, then its etag/reference in progress |
| Finishing branch | Pull/read all five roles; check approvals, reviewed HEAD and task verification | Push completion with results, residual issues and PR URL if created; push progress with completion etag before cleanup |

For a fresh empty spec/plan/progress node, drafting starts without approval;
execution still requires the actual approvals. Never manufacture approval to
advance a stage. Any spec or plan etag change requires comparing the fetched
content against what was approved. Require renewed human approval before
dependent implementation; do not infer that a change is too minor to matter.
If HEAD changed since review,
review the new changes before claiming completion. These checks are an agent
responsibility in this pilot, not a server-enforced approval system.

On resume, wiki progress supersedes stale local completion lines only after a
successful pull. Verify cited commits are in the checkout; fetch or report the
missing checkout state rather than repeating or inventing completed work.
The progress working copy must match the path resolved by `sdd-workspace` for the
configured plan. Verify the mapping before running task helpers. After helpers
append progress, push it. Do not proceed after an unacknowledged push.

One controller writes progress in a working directory. Give subagents the
relevant fetched text, source paths+etags, and Git revisions; they return changes
and evidence to the controller. They must not concurrently push the controller's
working copy. Independent worktrees have independent baselines; etags detect
conflicting writes but do not provide task ownership or prevent duplicate work.

## Failure, conflict, and cleanup

- If a pull refuses dirty or previously unmanaged local content, preserve it
  outside the mapped path first. Fetch remote into a clean working copy, then
  reconcile deliberately. Never discard pending work to make a pull pass.
- An etag conflict or ambiguous write result stops the handoff. Preserve local
  content and inspect remote content/revisions. Merge intentionally and obtain
  a fresh baseline before pushing. Do not auto-retry with a new etag, remove
  `--expected-etag`, or mark unsent work complete.
- No wiki access means no new dependent task dispatch. Already-running local
  work can be preserved with an explicit pending-sync report.
- Each artifact push is separate. Persist spec/plan/review/completion before
  publishing a progress reference to its acknowledged revision. A partially
  successful sequence remains pending, never globally complete.
  Validation across source documents and progress is non-atomic too; a source
  can change after checking it. Use one controller and recheck at stage
  boundaries. Do not describe this pilot as transactional approval enforcement.
- Before deleting a plan workspace or removing a worktree, ensure its progress,
  required evidence and final review are durable and retrievable from the wiki
  or linked Git/CI artifacts. An ephemeral local path is not durable evidence.
  Preserve the working directory on sync failure. Never delete a directory that
  contains the selected config or the only copy of bridge snapshots during an
  active workflow. A later session can reconstruct baselines by pulling into an
  empty working copy after the previous workflow has been durably handed off.

See `docs/kinic/README.md` in this fork for setup and pilot limitations.
