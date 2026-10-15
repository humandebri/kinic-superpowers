#!/usr/bin/env python3
"""Load only local Kinic project context. Never contact wiki or mutate files."""
import json
from pathlib import Path
import shlex
import sys

# Avoid import cache writes in the installed plugin or application checkout.
sys.dont_write_bytecode = True
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / 'scripts'))


def context_for(payload):
    from kinic_project import Project, ProjectError, discover, fingerprint
    cwd = payload.get('cwd')
    session = payload.get('session_id')
    if not isinstance(cwd, str) or not isinstance(session, str) or not session:
        return ''
    root, config_path = discover(Path(cwd))
    if not config_path or not Path(config_path).is_file():
        return ''
    config_path = Path(config_path)
    root = Path(root)
    try:
        config = json.loads(config_path.read_text())
        if not isinstance(config, dict) or config.get('version', 1) not in (1, 2):
            raise ValueError('unsupported configuration version')
    except (ValueError, OSError) as error:
        return f'Kinic Superpowers configuration is invalid at {config_path}: {error}. Repair it before workflow operations; do not fall back to local-only work.'
    quote = shlex.quote
    command = f'python3 {quote(str(PLUGIN_ROOT / "scripts" / "kinic-workflow.py"))} --config {quote(str(config_path))}'
    command += f' --project-root {quote(str(root))}'
    bootstrap = ('Load kinic-superpowers:using-superpowers and its references/kinic-workflow.md before choosing a development workflow. '
                 'The hook reads local settings only; wiki content and readiness have not been verified. ')
    if config.get('version', 1) == 1:
        return bootstrap + f'Legacy single workflow configured. Run `{command} check`, then safely pull/read the configured spec, plan, progress and review before resuming. Preserve dirty copies; never invent approvals.'
    try:
        project = Project(root, config_path)
        binding_path = project._binding_path(session)
    except (ProjectError, OSError, ValueError, TypeError) as error:
        return f'Kinic Superpowers configuration is invalid at {config_path}: {error}. Repair before workflow operations.'
    command += f' --session {quote(session)}'
    try:
        binding = json.loads(binding_path.read_text()) if binding_path.is_file() else None
        if binding is not None:
            if not isinstance(binding, dict) or binding.get('session_id') != session or binding.get('project_fingerprint') != fingerprint(config):
                raise ValueError('session binding does not match this project')
            workflow_id = binding.get('workflow_id')
            if not isinstance(workflow_id, str) or not workflow_id:
                raise ValueError('session binding has no workflow ID')
    except (OSError, ValueError) as error:
        return bootstrap + f'Local session binding is invalid: {error}. Inspect and repair it; do not choose another workflow or use the latest one.'
    if binding is None:
        return bootstrap + (f'No workflow selected for this session. Run `{command} workflow list`; ask which existing workflow to use, then run '
                            f'`{command} workflow use WORKFLOW_ID`. If the user requests a new workflow, run `{command} workflow new --title TITLE` '
                            'and bind the returned ID with workflow use. Never automatically select the most recent workflow.')
    return bootstrap + (f'This session is bound to workflow {quote(workflow_id)}. Keep that selection after resume/compaction. '
                        f'Run `{command} check`, then safely pull/read spec, plan, progress and review using the same command prefix '
                        '(for example `pull progress`). Verify approved etags, reviewed commit and current progress before implementation. '
                        'Remote changes or a failed sync require reconciliation; never switch to a newer workflow automatically.')


def main():
    try:
        payload = json.load(sys.stdin)
        context = context_for(payload) if isinstance(payload, dict) else ''
    except (OSError, ValueError, ImportError) as error:
        context = f'Kinic Superpowers local hook could not load project context: {error}. Inspect the local plugin/config before workflow operations.'
    if context:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': context}}))


if __name__ == '__main__':
    main()
