# Kinic Wiki storage and recovery

Applies only when this checkout or its primary checkout has a valid
`.kinic-superpowers.json`. Wiki is the document authority; Git remains the code
and commit authority. Follow the upstream skills for task size, design approval,
plan contents, execution mode, review loops and final reporting. This reference
changes storage and recovery, not those development rules.

## Classify first

Use brainstorming's existing sizing rules. A question or quick clear change
needs no new workflow/documents merely because this project is configured.
Explicit throwaway spikes retain upstream's reduced process. A small description
can remain in chat. For a written project or resuming an existing case, resolve
the workflow before accessing its documents. An existing bound case remains bound
when doing a small follow-up; do not switch it implicitly.

## Connection and selection

Use the exact adapter prefix from SessionStart (installed script, --config,
--project-root, --session). Without a hook, resolve the adapter from this installed
skill at `../../scripts/kinic-workflow.py` and use the actual chat ID. Quote paths.
Setup uses `init --inspect`, the saved/linked writable DB, and repository-derived
project name; `init` saves the verified connection. `project register` registers
the repository in the Wiki. No secret keys or tokens are stored. Keep authorized
identity pinned; a mismatch stops access, never switches identities.

For a case needing durable documents, `workflow list` lists registered cases.
Use the user's intended case with `workflow use ID`. For a requested new case,
`workflow new --title TITLE` registers it without creating document placeholders.
With --session it binds the result. No selection means ask, not guess the latest.
`ready` describes registration, not design approval or implementation completion.

`status` is local cached state. `check` reads remote freshness; safely `pull ROLE`
and read the needed registered documents before resuming. `not_created` means
no document was registered, not a lost file; a missing registered file is an
error. Preserve dirty local copies and reconcile instead of overwriting them.
Old configuration/manifest versions keep their existing mappings; do not recreate
or rewrite their pages as part of reading or starting a session.

## Author and save only actual documents

Keep upstream filenames and content:

- Design: `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`.
- Plan: `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`.
- Ledger: run the installed `sdd-workspace PLAN_FILE` helper through bash and use
  its returned directory. Pass PLAN_FILE relative to the repository root so it
  survives another checkout. Its first line remains
  `# SDD ledger — plan: <plan file path>`. Preserve completion/ruling line formats.

After authoring a new document, register and publish it with
`workflow document ROLE --file REPO_RELATIVE_PATH`. For existing registered
documents, use `push ROLE`. Confirm the acknowledged Wiki path and etag before
handoff. Replace upstream's document-commit step with that acknowledgement;
continue committing code normally. Local Markdown is a working copy, not a
second authority. In plans, retain a reachable Spec reference and its Wiki path
and acknowledged revision when one exists; do not invent a spec for a plan that
upstream permits to proceed without one.

Use spec/plan/progress roles for their corresponding actual documents. Optional
review/completion roles hold real reports when needed; they are never prerequisite
empty pages. Use `workflow index` after case/document updates to refresh the
project navigation. Update the human-readable current status with
`workflow state --summary TEXT` when it changes; this is not an approval gate.
Existing custom indexes are not silently overwritten.

## Execution and recovery

Restore the plan and its ledger into this worktree. Verify the ledger's plan
identity, Git commits, and actual pending work. Use the selected execution
skill's helpers, task completion checks and review policy unchanged. Save ledger
updates after completed tasks and rulings so another chat can recover them.

An etag change is a concurrency signal. Reconcile the actual content, then use
upstream's rules to decide whether a design decision needs human input or a plan
correction can be ruled on by the executor. Storage does not manufacture approval
or introduce approval gates. Inline final fixes retain inline's TDD fix pass;
subagent execution retains its own scoped re-review loop.

One controller owns artifact writes. Subagents receive the needed plan/spec,
Wiki references and Git revisions and return evidence. Copies, baseline etags,
helper workspaces and chat bindings stay separate per worktree.

## Conflict, completion and cleanup

On conflict or uncertain acknowledgement preserve local content, inspect remote
content, and reconcile deliberately. Never remove the etag guard or blindly retry
with a fresh etag. Unavailable Wiki blocks dependent handoffs, not inspection or
preservation of already completed local work. Report pending synchronization.

Before upstream's local workspace cleanup, save the actual ledger and final
report containing its exhaustive rulings/deferred findings, verification results,
and Git/PR references. The report may be in the ledger; a separate completion
page is optional. Confirm saved content can be read back, update the index, then
remove only the intended local execution workspace. Keep connection and baseline
state required by other cases. Do not publish raw transcripts or transient test
logs as knowledge. Live test fixtures belong under `/Testing/kinic-superpowers/`
and are removed after their durable test report is captured.

Per-document saves are not a multi-document transaction, approval enforcement,
or a distributed task lease.
