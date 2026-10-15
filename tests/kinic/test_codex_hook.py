"""Codex hook must be deterministic, local-only, and session scoped."""
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
HOOK = ROOT / 'hooks' / 'codex-session-start.py'


class CodexHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = pathlib.Path(self.tmp.name)

    def config(self, data=None):
        path = self.project / '.kinic-superpowers.json'
        path.write_text(json.dumps(data or {'version': 2, 'database_id': 'db_test', 'scope': '/Knowledge/tests', 'cli': '/bin/false', 'canister_id': 'test-canister', 'replica_host': 'https://icp0.io', 'identity': {'principal': 'abc', 'allow_non_ii_identity': True}}))
        return path

    def run_hook(self, session='chat-a', source='startup', cwd=None):
        result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({'session_id': session, 'cwd': str(cwd or self.project), 'source': source}), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout or '{}')
        if data:
            self.assertEqual(data['hookSpecificOutput']['hookEventName'], 'SessionStart')
        return data.get('hookSpecificOutput', {}).get('additionalContext', '')

    def test_no_config_is_silent(self):
        self.assertEqual(self.run_hook(), '')

    def test_unselected_includes_exact_list_and_use_guidance(self):
        self.config()
        context = self.run_hook(session="a '; touch injected")
        self.assertIn('workflow list', context)
        self.assertIn('workflow use', context)
        self.assertIn('--session', context)
        self.assertIn(str(ROOT / 'scripts' / 'kinic-workflow.py'), context)
        self.assertIn('kinic-superpowers:using-superpowers', context)
        self.assertFalse((self.project / 'injected').exists())

    def test_present_malformed_config_is_actionable(self):
        (self.project / '.kinic-superpowers.json').write_text('{')
        context = self.run_hook()
        self.assertIn('invalid', context.lower())
        self.assertNotIn('workflow new', context)

    def test_invalid_version_is_actionable(self):
        self.config({'version': 999})
        self.assertIn('invalid', self.run_hook().lower())

    def test_missing_saved_endpoint_is_actionable_without_fallback(self):
        path = self.config()
        data = json.loads(path.read_text())
        del data['canister_id']
        path.write_text(json.dumps(data))
        context = self.run_hook()
        self.assertIn('invalid', context.lower())
        self.assertNotIn('workflow new', context)

    def test_legacy_remains_single_workflow(self):
        self.config({'version': 1, 'database_id': 'db_test', 'artifacts': {}})
        context = self.run_hook()
        self.assertIn('legacy', context.lower())
        self.assertIn('pull', context)
        self.assertNotIn('workflow use', context)

    def test_legacy_shared_worktree_command_names_current_checkout(self):
        self.config({'version': 1, 'database_id': 'db_test', 'artifacts': {}})
        admin = self.project / '.git/worktrees/linked'
        admin.mkdir(parents=True)
        (admin / 'commondir').write_text('../..')
        checkout = self.project / 'linked'
        checkout.mkdir()
        (checkout / '.git').write_text('gitdir: ' + str(admin))
        context = self.run_hook(cwd=checkout)
        self.assertIn('Legacy', context)
        self.assertIn('--project-root ' + str(checkout.resolve()), context)

    def test_nested_directory_discovery_and_no_writes(self):
        self.config()
        nested = self.project / 'src'
        nested.mkdir()
        before = {str(p): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        self.assertIn('workflow list', self.run_hook(cwd=nested))
        after = {str(p): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_resume_compact_use_same_local_context(self):
        self.config()
        self.assertEqual(self.run_hook(source='resume'), self.run_hook(source='compact'))

    def bind(self, session, workflow='00000000-0000-4000-8000-000000000001', fingerprint_value=None):
        config = json.loads((self.project / '.kinic-superpowers.json').read_text())
        signature = hashlib.sha256(json.dumps([config.get(k) for k in ('database_id', 'canister_id', 'replica_host', 'scope')], sort_keys=True).encode()).hexdigest()
        directory = self.project / '.superpowers' / 'kinic' / 'sessions'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (hashlib.sha256(session.encode()).hexdigest() + '.json')).write_text(json.dumps({'session_id': session, 'workflow_id': workflow, 'project_fingerprint': fingerprint_value or signature}))

    def test_selected_workflow_retained_on_resume_and_compact(self):
        self.config()
        self.bind('chat-a')
        resume = self.run_hook(source='resume')
        self.assertEqual(resume, self.run_hook(source='compact'))
        self.assertIn('00000000-0000-4000-8000-000000000001', resume)
        self.assertIn('check', resume)
        self.assertNotIn('workflow use', resume)
        self.assertIn('workflow list', self.run_hook(session='chat-b'))

    def test_mismatched_binding_blocks_recovery(self):
        self.config()
        self.bind('chat-a', fingerprint_value='another-project')
        context = self.run_hook()
        self.assertIn('binding is invalid', context)
        self.assertNotIn('workflow use', context)

    def test_hook_invokes_no_subprocess_or_network_and_writes_nothing(self):
        self.config()
        spec = importlib.util.spec_from_file_location('codex_hook_tested', HOOK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch('subprocess.run', side_effect=AssertionError('subprocess forbidden')), patch('socket.socket', side_effect=AssertionError('network forbidden')), patch.object(pathlib.Path, 'write_text', side_effect=AssertionError('write forbidden')), patch.object(pathlib.Path, 'mkdir', side_effect=AssertionError('mkdir forbidden')):
            self.assertIn('workflow list', module.context_for({'cwd': str(self.project), 'session_id': 'chat-a'}))

    def test_worktree_shared_config_keeps_current_root_and_bindings(self):
        self.config()
        main_git = self.project / '.git'
        admin = main_git / 'worktrees' / 'linked'
        admin.mkdir(parents=True)
        (admin / 'commondir').write_text('../..')
        worktree = self.project / 'linked'
        worktree.mkdir()
        (worktree / '.git').write_text('gitdir: ' + str(admin))
        self.bind('chat-a')
        context = self.run_hook(cwd=worktree)
        self.assertIn('workflow list', context)
        self.assertIn('--project-root ' + str(worktree.resolve()), context)
        self.assertIn(str((self.project / '.kinic-superpowers.json').resolve()), context)

    def test_manifest_targets_codex_specific_hook(self):
        manifest = json.loads((ROOT / '.codex-plugin' / 'plugin.json').read_text())
        self.assertEqual(manifest['name'], 'kinic-superpowers')
        self.assertEqual(manifest['hooks'], './hooks/codex-hooks.json')
        definition = json.loads((ROOT / 'hooks' / 'codex-hooks.json').read_text())
        entry = definition['hooks']['SessionStart'][0]
        self.assertIn('compact', entry['matcher'])
        self.assertIn('resume', entry['matcher'])
        self.assertEqual(entry['hooks'][0]['command'], 'python3 "${PLUGIN_ROOT}/hooks/codex-session-start.py"')


if __name__ == '__main__':
    unittest.main()
