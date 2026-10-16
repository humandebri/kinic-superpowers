"""CLI dispatch contracts for saved connections and chat-bound workflows."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/kinic-workflow.py'
spec = importlib.util.spec_from_file_location('project_cli', SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Mock()
        self.project.version = 2
        self.project.root = self.root
        self.project.config_path = self.root / '.kinic-superpowers.json'
        self.project.config = {'version': 2}
        self.project.resolve.return_value = {'id': 'a', 'title': 'Example feature'}
        self.project.new.return_value = {'id': 'a', 'state': 'ready'}
        self.project.list.return_value = [{'id': 'a', 'state': 'ready'}]
        self.project.use.return_value = {'workflow_id': 'a', 'session_id': 'chat-a'}
        self.module = types.SimpleNamespace(
            ProjectError=type('ProjectError', (Exception,), {}),
            Project=Mock(return_value=self.project), initialize=Mock(return_value={'version': 2}))

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(sys.modules, {'kinic_project': self.module}), \
                patch.object(sys, 'argv', [str(SCRIPT), *args]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return bridge.main(), out.getvalue(), err.getvalue()

    def test_init_accepts_options_after_command(self):
        code, out, _ = self.invoke('init', '--database-id', 'db-test', '--scope', '/Knowledge/tests',
                                   '--cli', '/custom/kinic', '--allow-non-ii-identity')
        self.assertEqual(code, 0)
        self.assertIn('2', out)
        self.assertEqual(self.module.initialize.call_args.kwargs['database_id'], 'db-test')
        self.assertTrue(self.module.initialize.call_args.kwargs['allow_non_ii_identity'])

    def test_init_can_discover_settings_without_manual_ids_or_paths(self):
        code, _, _ = self.invoke('init', '--inspect')
        self.assertEqual(code, 0)
        options = self.module.initialize.call_args.kwargs
        self.assertIsNone(options['database_id'])
        self.assertIsNone(options['scope'])
        self.assertTrue(options['inspect'])

    def test_new_can_bind_current_chat(self):
        code, _, _ = self.invoke('workflow', 'new', '--title', 'Example', '--session', 'chat-a')
        self.assertEqual(code, 0)
        self.project.new.assert_called_once_with(title='Example', resume=None)
        self.project.use.assert_called_once_with('a', 'chat-a')

    def test_explicit_resume_without_title(self):
        code, _, _ = self.invoke('workflow', 'new', '--resume', 'a')
        self.assertEqual(code, 0)
        self.project.new.assert_called_once_with(title=None, resume='a')

    def test_list_does_not_implicitly_select(self):
        code, out, _ = self.invoke('workflow', 'list')
        self.assertEqual(code, 0)
        self.assertIn('ready', out)
        self.project.use.assert_not_called()

    def test_use_requires_session(self):
        with self.assertRaises(SystemExit):
            self.invoke('workflow', 'use', 'a')

    def test_read_only_status_resolves_without_remote(self):
        data = {'version': 1, 'database_id': 'db-test', 'artifacts': {
            'spec': {'path': '/Knowledge/a/spec.md', 'local': '.superpowers/workflows/a/spec.md'}}}
        self.project.workspace_data.return_value = data
        code, out, _ = self.invoke('--session', 'chat-a', 'status', 'spec')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['workflow_id'], 'a')
        self.assertEqual(json.loads(out)['workflow_title'], 'Example feature')
        self.project.resolve.assert_called_once_with(session='chat-a', workflow_id=None, remote=False)
        self.project.transport.assert_not_called()
        self.project.cache_manifest.assert_not_called()

    def test_explicit_workflow_pull_preserves_manifest_for_local_status(self):
        from test_project import Fake, p as runtime, legacy_new
        fake = Fake()
        runtime.initialize(self.root, 'db', '/Knowledge/tests', run=fake)
        primary = runtime.Project(self.root, run=fake)
        primary.config.pop('registry_required', None)
        primary.config_path.write_text(json.dumps(primary.config))
        manifest = legacy_new(primary, 'Automated feature')
        checkout = self.root / 'automation'
        checkout.mkdir()
        project = runtime.Project(checkout, config_path=primary.config_path, run=fake)
        self.module.Project.return_value = project
        self.module.ProjectError = runtime.ProjectError
        before = {str(path): path.read_bytes() for path in checkout.rglob('*') if path.is_file()}
        code, _, _ = self.invoke('--workflow', manifest['id'], 'check', 'spec')
        self.assertEqual(code, 1)  # untracked; check must remain read-only
        self.assertEqual(before, {str(path): path.read_bytes() for path in checkout.rglob('*') if path.is_file()})
        code, _, _ = self.invoke('--workflow', manifest['id'], 'pull', 'spec')
        self.assertEqual(code, 0)
        calls = len(fake.calls)
        code, out, _ = self.invoke('--workflow', manifest['id'], 'status', 'spec')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['workflow_title'], 'Automated feature')
        self.assertFalse(json.loads(out)['dirty'])
        self.assertEqual(len(fake.calls), calls)

    def test_lazy_document_cli_publishes_and_checks_only_authored_roles(self):
        from test_project import Fake, p as runtime
        fake = Fake()
        runtime.initialize(self.root, 'db', '/Knowledge/tests', run=fake)
        project = runtime.Project(self.root, run=fake)
        from kinic_registry import register
        register(project)
        manifest = project.new('Lazy feature')
        project.use(manifest['id'], 'chat-a')
        self.module.Project.return_value = project
        self.module.ProjectError = runtime.ProjectError
        for command in ('status', 'check'):
            code, out, error = self.invoke('--session', 'chat-a', command)
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(out)['state'], 'no_documents')
            code, out, error = self.invoke('--session', 'chat-a', command, 'spec')
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(out)['state'], 'not_created')
        local = 'docs/superpowers/specs/2026-10-16-cli-design.md'
        path = self.root / local
        path.parent.mkdir(parents=True)
        path.write_text('# Design\n\nThe new feature does a useful thing.\n')
        code, out, error = self.invoke('--session', 'chat-a', 'workflow', 'document', 'spec', '--file', local)
        self.assertEqual(code, 0, error)
        code, out, error = self.invoke('--session', 'chat-a', 'check')
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(out)['state'], 'clean')
        code, out, error = self.invoke('workflow', 'index')
        self.assertEqual(code, 0, error)
        self.assertIn('Lazy feature', json.loads(out)['content'])
        manifest = project.resolve('chat-a')
        del fake.nodes[manifest['artifacts']['spec']['path']]
        code, out, error = self.invoke('--session', 'chat-a', 'check', 'spec')
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)['state'], 'error')

    def test_new_configuration_requires_registration_before_listing(self):
        from test_project import Fake, p as runtime
        fake = Fake()
        config = runtime.initialize(self.root, 'db', '/Knowledge/tests', run=fake)
        self.assertTrue(config.get('registry_required'))
        project = runtime.Project(self.root, run=fake)
        self.module.Project.return_value = project
        self.module.ProjectError = runtime.ProjectError
        before = len(fake.calls)
        code, _, error = self.invoke('workflow', 'list')
        self.assertEqual(code, 1)
        self.assertIn('project register', error)
        self.assertEqual(len(fake.calls), before)

    def test_workflow_new_registers_and_rejects_same_named_foreign_repository(self):
        from test_project import Fake, p as runtime
        import kinic_registry
        fake = Fake()
        for index, repository in enumerate(('github.com/a/app', 'github.com/b/app')):
            root = self.root / str(index) / 'app'
            root.mkdir(parents=True)
            runtime.initialize(root, 'db', '/Knowledge/projects/app', run=fake)
            project = runtime.Project(root, run=fake)
            self.module.Project.return_value = project
            self.module.ProjectError = runtime.ProjectError
            with patch.object(kinic_registry, 'ProjectError', runtime.ProjectError), patch.object(kinic_registry, 'propose', return_value={'project_name': 'app', 'repository_key': repository}):
                code, out, error = self.invoke('workflow', 'new', '--title', 'Feature')
            if index == 0:
                self.assertEqual(code, 0, error)
                self.assertTrue(project.config.get('project_id'))
                first_id = json.loads(out)['id']
            else:
                self.assertEqual(code, 1)
                self.assertIn('collision', error)
        manifests = [n for path, n in fake.nodes.items() if path.endswith('/manifest.json')]
        self.assertEqual(len(manifests), 1)
        self.assertEqual(json.loads(manifests[0]['content'])['id'], first_id)

    def test_discovered_legacy_worktree_does_not_use_main_checkout_copy(self):
        main = self.root / 'main'
        checkout = self.root / 'worktree'
        main.mkdir()
        checkout.mkdir()
        config = main / '.kinic-superpowers.json'
        config.write_text(json.dumps({'version': 1, 'database_id': 'db-test', 'artifacts': {
            'spec': {'path': '/Knowledge/spec.md', 'local': 'spec.md'}}}))
        self.project.version = 1
        self.project.root = checkout
        self.project.config_path = config
        code, out, _ = self.invoke('status', 'spec')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['local'], str((checkout / 'spec.md').resolve()))


if __name__ == '__main__':
    unittest.main()
