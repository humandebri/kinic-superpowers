# Upstream contract and intentional storage adaptations

Baseline: obra/superpowers `bb92a77741419a4ab5f06e711a283343f1ada0c3` (v7.0.0).
Research checkout: `/Volumes/KINGSTON/KINIC/superpowers-upstream`.
The user approved this redesign on 2026-10-16. Wiki remains the document authority.

| Upstream contract | Previous fork divergence | Retained adaptation / correction |
|---|---|---|
| brainstorming: quick clear tasks execute directly; small descriptions can live in chat; explicit spikes skip full process | Every configured interaction first selected a five-page workflow | Classify work first; no document provisioning for a question, typo or throwaway spike |
| Written designs use `docs/superpowers/specs/YYYY-MM-DD-topic-design.md` | UUID document copies; empty spec precreated | Same authored file name/local path; acknowledge Wiki version instead of committing the document |
| Plans use `docs/superpowers/plans/YYYY-MM-DD-feature.md`, including Goal, Architecture, Tech Stack, Spec, constraints, review focus and actionable tasks | Mandatory five-page graph before planning | Preserve upstream plan content and creation conditions; register actual authored document only |
| Inline and subagent execution have different review/fix loops | Shared protocol required reviewed HEAD after every change | Each execution skill owns its gates; storage protocol cannot add a re-review |
| Executor rules on bounded plan defects and records rulings | Any spec/plan etag change required renewed approval | Etags detect concurrent changes, not semantic approval; preserve upstream rulings and actual human decisions |
| Ledger first line is `# SDD ledger — plan: <plan file path>` | Generated `# title: progress` / Design template | Preserve exact helper ledger format; restore into helper-resolved workspace |
| `sdd-workspace` uses plan basename plus marker-based collision handling | UUID directory forced | Use helper-compatible local mapping; validate plan identity on resume |
| Final response includes exhaustive rulings/deferred minors; workspace then removed | All five roles including completion mandatory | Save actual final report/ledger before local cleanup; no mandatory empty review/completion pages |
| Code and commits remain in Git | Wiki references sometimes treated as sufficient proof | Verify cited Git commits and test evidence locally; Wiki cannot substitute for code verification |

## Storage boundary

Repository project registration, per-chat selection, conditional publication,
conflict detection, worktree-local copies, and a navigable project index are Kinic
features. They do not decide whether a task needs a design, review or new approval.
New workflow records contain no placeholder documents. Missing unregistered
documents are distinct from lost registered documents.

## Validation record

Before edits, a fresh evaluator traced six scenarios against the original protocol:
quick typo, throwaway spike, inline plan, subagent plan, compaction, cleanup.
Failures reproduced instruction conflicts above. This was an instruction trace,
not a live CLI run; native installed-plugin scenarios are a separate acceptance check.
The evaluator also confirmed that old UUID local paths did align by basename:
the resume defect was the ledger header, not a directory mismatch.
