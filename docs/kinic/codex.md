# Codex local plugin setup

This fork retains Superpowers history and MIT attribution. The Codex plugin is
named `kinic-superpowers`; use `kinic-superpowers:...` for its skills. It starts
workflow guidance only in projects with `.kinic-superpowers.json`. Existing
upstream Claude/Cursor packaging is retained but this version's automatic
project/session integration is verified separately for Codex.

## Install and trust

Use a **local marketplace**, not a public directory submission. Lifecycle hooks
are currently supported for manually installed Codex desktop plugins. See the
[official plugin packaging guide](https://developers.openai.com/plugins/build/plugins)
and [official hooks guide](https://learn.chatgpt.com/docs/hooks).
Use this local installation route for the fork. Retained upstream archive and
public-release scripts are outside this integration and are not a supported
way to distribute its runtime and hooks.

This checkout includes a local marketplace. Install it with the normal Codex CLI:

```bash
codex plugin marketplace add /absolute/path/to/kinic-superpowers --json
codex plugin add kinic-superpowers@kinic-superpowers-local --json
```

To host the plugin inside another repository, place or copy it under
`<repo>/plugins/kinic-superpowers` and merge this entry into
`<repo>/.agents/plugins/marketplace.json`:

```json
{
  "name": "local-kinic",
  "plugins": [{
    "name": "kinic-superpowers",
    "source": {"source": "local", "path": "./plugins/kinic-superpowers"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Developer Tools"
  }]
}
```

Paths resolve from the repository root. For a personal marketplace use
`~/.agents/plugins/marketplace.json` and an appropriate plugin source path;
merge the existing file rather than replacing it. Enable the local plugin in
the trusted project's `.codex/config.toml`, preserving all existing settings:

```toml
[plugins."kinic-superpowers@local-kinic"]
enabled = true
```

Restart the desktop app, check the plugin appears, and review/trust its hook
in `/hooks`. Project configuration must be trusted as well. Installing does not
automatically trust hooks; changed hook definitions require renewed review.
Do not overwrite `.codex/hooks.json`: the explicit manifest hook path loads
alongside existing hooks. Keep Python 3 on the hook process's PATH.

## Initialize and use

In the application checkout, ask Codex: "Set up this project for Kinic Wiki."
The `setup-kinic` skill applies even before configuration exists. It discovers
the CLI connection and databases, reuses a saved/linked or sole writable DB, and
generates a project scope. With multiple choices it asks for a database by name;
the agent handles the ID. An earlier explicit database choice in the conversation
can be reused. Identity authorization must come from the human; never switch it.

The underlying commands are:

```bash
python3 /absolute/plugin/path/scripts/kinic-workflow.py init --inspect
python3 /absolute/plugin/path/scripts/kinic-workflow.py init
```

If the CLI is outside PATH, add `--cli /absolute/path/to/kinic-vfs-cli` once at
initialization. For a human-authorized non-II identity, also add
`--allow-non-ii-identity` once. Both settings and the exact principal are saved;
normal workflow commands need neither connection nor authentication flags.
Optional `--database-id` and `--scope` still override discovery. An explicit scope
must be a canonical path below `/Knowledge/`. A generated scope includes the
repository name and a short hash of its location to separate same-named clones;
once saved, the scope is reused even if the repository moves.

Open a **new chat** in the configured checkout and request development normally.
The hook supplies an exact shell-quoted command with config, checkout and
session ID; the agent lists cases and asks which to use, or creates a new one
when requested. Creation provisions all five wiki pages automatically. It binds
the case with `workflow use ID`; normal `check`, `pull`, `push` and `status` then
use this chat's selection. Another chat can choose a different case. Compaction
or resuming the same chat preserves its selection.

The hook itself performs no network requests, commands, writes, or page creation.
A binding is local guidance, not proof the remote case is ready: the agent must
verify remote state and read the documents before resuming implementation.

## Acceptance check

Use the installed plugin in a clean Codex desktop chat, with no manual skill
invocation. Ask `Let's make a react todo list` in a configured disposable project.
Confirm that it resolves the case and invokes brainstorming before editing code.
Resume the chat and compact it; confirm the same selected case is retained.
Run a second chat with a different case and confirm no selection leakage.
Record the actual transcript and hook trust status. A hook unit test or a
subagent reading these instructions does **not** prove this acceptance check.

After editing this plugin, refresh its installed copy and restart the app before
repeating the clean-chat test. Hook tests are `python3 -m unittest discover -s
tests/kinic -p test_codex_hook.py` from the plugin checkout.

## Implementation validation (2026-10-15)

The hook suite covers silent unconfigured projects, actionable
invalid configuration, legacy configuration, selected/unselected sessions,
resume/compact consistency, malformed bindings, shell-sensitive session IDs,
nested discovery, shared worktree configuration with isolated bindings,
manifest wiring, and no subprocess/network/file mutations.

The writing-skills evaluation used a fresh subagent before changing the
protocol. Baseline failures were missing v2/session instructions, manual page
provisioning, and a global skill trigger outside configured projects. The same
agent then evaluated the revised instructions against the three baseline
scenarios and five pressure variations: stale local completion, changed
approved spec, dirty working copy, malformed binding, and installation paths
containing spaces. It found a fallback path error and an implicit binding
inspection step; both were fixed and the targeted retest passed. This is
instruction evaluation, not an installed Codex desktop acceptance transcript.
The namespace and scope edits in other skills are mechanical; their upstream
behavioral suites were not rerun individually.

Installed-plugin native Codex CLI session evidence and live-database results are
recorded in [onboarding validation](onboarding-2026-10-15.md). CLI session results
are identified separately from desktop UI acceptance.
