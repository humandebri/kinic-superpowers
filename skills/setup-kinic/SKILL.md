---
name: setup-kinic
description: "Use when the user asks to connect, initialize or set up the current project for Kinic Wiki or Kinic Superpowers, including when no project configuration exists yet."
---

# Set up Kinic for this project

Apply this skill to an explicit setup request. An unrelated development request
in an unconfigured repository does not authorize initialization.

Resolve this installed skill's directory and use its `../../scripts/kinic-workflow.py`,
shell-quoting the absolute adapter path. Run from the user's application checkout;
the adapter need not be present in that repository.

1. Run `python3 ADAPTER init --inspect`. It reads CLI connection settings,
   identity and accessible databases without saving settings or creating pages.
   Use the CLI on PATH; if missing, locate an installed executable or report
   the missing prerequisite. Do not ask the user to construct a command/path.
2. Reuse the saved database, CLI-linked database, or sole active writable
   database returned by inspection. When `selection_required` is true, use a
   database already explicitly chosen by the user in this conversation, if it
   appears among the candidates. Otherwise ask which database **by name**;
   retain its ID internally. Do not guess from recency or choose an arbitrary DB.
   With no writable candidates, explain the access issue; do not create a DB.
3. Run `python3 ADAPTER init`, adding `--database-id ID` only when resolving
   an ambiguous choice. Omit `--scope`: the adapter generates a unique project
   scope and reuses it on subsequent runs. Honor an explicitly requested scope.
   A v1 configuration needs explicit `--migrate` to register its preserved pages;
   use it when the user requests migration, rather than replacing their config.
4. Report the selected database's name and that setup is saved. New workflow
   requests can now use `kinic-superpowers:using-superpowers`. Setup alone does
   not create an application workflow, imply approvals or start implementation.

Reuse existing human authorization for a non-II identity; supply
`--allow-non-ii-identity` during inspection/initialization when already authorized.
If authorization is missing, ask about the current identity once in plain
language. Never switch identity or bypass a principal mismatch. Keep CLI errors
as errors; no local-only fallback. Never save secret keys or tokens.
