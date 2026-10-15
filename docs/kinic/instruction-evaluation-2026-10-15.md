# Instruction evaluation — 2026-10-15

This is a writing-skills instruction evaluation, separate from a native Codex
installed-plugin session. The evaluator was a fresh-context subagent named
`/root/codex_plugin/skill_baseline`; it read the repository files and reported
its decisions without editing files or executing a development workflow.
The same evaluator was given the revised files for GREEN and targeted retests.
Its responses are preserved in the parent chat's collaboration tool history;
there is no exported standalone transcript file.

Files evaluated: `skills/using-superpowers/SKILL.md` and
`skills/using-superpowers/references/kinic-workflow.md`. Before the baseline,
the evaluator also checked the then-current adapter parser to distinguish
implemented commands from invented instructions.

## Baseline scenarios and observed failures

| Scenario | Observed decision or gap |
|---|---|
| A: plugin globally installed; unrelated project has no config; tiny bug fix | Wiki integration was conditional, but the generic skill still required invocation for any conversation and directed `superpowers:systematic-debugging`. No-config isolation conflicted with global process rules. |
| B: v2 config; session bound to workflow A; workflow B is newer; resume after compaction with a two-minute deadline | The then-current parser rejected v2 (`config version must be 1`). Neither instruction file defined session bindings or workflow IDs. Choosing A or B could not be justified from those instructions. |
| C: fresh v2 configured project; init complete; no wiki documents; request to start a feature | The parser rejected v2; the existing protocol additionally required five preprovisioned nodes and explicitly said the adapter did not create them. No creation/recovery route was supplied. |

The evaluator did not invent a workflow selector or node layout. It explicitly
reported that `init`, workflow creation/list/selection and session flags were
unsupported by the baseline parser. Runtime implementation was handled
separately; this evaluation does not claim agent execution of those commands.

## Changes and GREEN retest

The protocol now describes v2 workflow listing, creation with automatic five-page
provisioning, binding the returned or chosen workflow to the current session,
and retaining that binding even when a newer case exists. It forbids guessing
session IDs or artifact paths and provides a scoped command prefix. The
bootstrap/skill discovery now applies to configured projects.

The evaluator reread the revised files and reported:

- A: protocol returns workflow choice to the host; no initialization/wiki action.
- B: retain A, check remote state, preserve dirty copies, pull/read stage documents,
  validate approval etags and commits; the deadline grants no exception.
- C: list, create the requested new case, provision five documents, bind its ID,
  check and pull/read before brainstorming; no separate provisioning question.
- Stale local completion: successful wiki progress pull takes precedence;
  cited commits must exist before resuming.
- Changed approved spec etag: compare content and obtain renewed approval before
  dependent implementation.
- Dirty copy: preserve outside the mapped path and reconcile deliberately.
- Malformed binding: block recovery rather than choose the latest workflow.
- Install path containing spaces: reuse the hook's exact command prefix.

GREEN found three residual gaps: the fallback script path went one directory
too high; generic bootstrap wording still conflicted with no-config isolation;
and binding inspection was implicit. These were fixed by using
`../../scripts/kinic-workflow.py` relative to the skill directory, explicitly
requiring shell quoting, adding an early no-config return, and documenting
`status` with the same session prefix as the inspection operation.

## Targeted final retest and limits

The evaluator reread both files and reported: “All three previously reported
instruction gaps are resolved,” with no remaining gaps in this targeted check.
The earlier three scenarios and five pressure variations remained compliant.

This was one fresh evaluator with iterative follow-ups, not multiple independent
sessions or five repeated samples per wording variant. Other skills received
mechanical namespace/scope changes; their upstream behavioral suites were not
rerun individually. Hook unit tests and native Codex integration evidence are
reported separately and must not be inferred from this instruction evaluation.
