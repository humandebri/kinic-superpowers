# Kinic Wiki workflow protocol

Applies only to configured Kinic Superpowers projects. Resolve configuration
upward from the current working directory, stopping at the Git checkout root;
a worktree can share the primary checkout’s connection settings. No config means
this fork does not choose or start a workflow. A present invalid config or an
unavailable wiki is an error, never permission to fall back to local-only work.

## Configuration and session selection

The SessionStart hook gives the exact installed adapter command prefix with
`--config`, current checkout `--project-root`, and `--session`. Reuse that prefix
for every operation; never assume the adapter is in the application repository.
When the hook is unavailable, resolve the script relative to this installed
skill (`../../scripts/kinic-workflow.py` from the skill directory) and use the actual current chat ID.
Shell-quote each interpreter, script, config, checkout and session argument,
including installation paths containing spaces. Never fabricate a session ID or infer a target from the latest workflow.

For a version 2 configuration:

1. With no bound workflow, run `workflow list`. Ask which existing workflow to
   select, or use the user's request for a new case to run
   `workflow new --title TITLE`. Creation automatically provisions the five
   documents and its manifest. Bind the chosen/returned ID with
   `workflow use ID`. Do not use an incompletely initialized workflow; rerun
   creation with `workflow new --resume WORKFLOW_ID`.
2. To inspect the existing binding without changing it, run `status` using the
   same session prefix; the adapter resolves that binding and reports errors
   rather than guessing. A binding belongs to this chat and checkout. Keep it on resume/compaction,
   even when a newer case exists. A malformed/mismatched binding blocks work.
   To change it, require the user's intended selection and `workflow use ID`.
3. Run `check`, then safely `pull ROLE` and read the fetched documents. Preserve
   dirty working copies and reconcile them before pulling. The manifest/cache
   supplies paths; never invent UUID folders or artifact mappings. `status`
   reports local known state only, while `check` reads remote freshness.
4. `push ROLE` after editing and require acknowledgment before a handoff.
   Automated commands may pass an explicit workflow ID using `--workflow`;
   otherwise use the session binding. Never select a different chat’s case.

Connection initialization is explicit: run `init --database-id DB --scope PATH`
with a user-selected destination. Identity authorization is pinned to its
principal and checked on use; do not switch identities or bypass a mismatch.
No secrets or raw session transcripts belong in wiki documents or settings.

Version 1 configuration remains a single workflow with its existing mappings.
Use `check`/`pull`/`push`/`status` directly; migration never overwrites its pages.
Do not copy a shared connection config into worktrees. Each checkout retains
its own document copies, baseline etags and chat bindings.

## Authority and recovery

Wiki artifacts are authoritative; local paths are working copies for task
helpers. Source editing and test execution stay in Git/local or CI. Use the
selected workflow’s paths and pass its config, workflow/session identity and
source etags into subagent briefs. One controller owns artifact writes.

Progress starts with a current-state summary (stage, next action, approval
references and blockers), followed by append-only history. Keep mutable
approval/state labels out of spec/plan snapshots. Store actual human approval
against exact spec/plan etags in progress; never manufacture approval.

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
