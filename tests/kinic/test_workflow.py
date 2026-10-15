"""Contract tests for wiki-backed artifacts; no network or credentials."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'kinic-workflow.py'
spec = importlib.util.spec_from_file_location('workflow', SCRIPT)
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


class FakeCLI:
    def __init__(self):
        self.node = dict(path='/Knowledge/work/spec.md', kind='file',
                         content='approved spec', etag='v1', metadata_json='{"owner":"team"}')
        self.calls = []
        self.conflict = False

    def __call__(self, args):
        self.calls.append(args)
        if 'read-node' in args:
            return dict(self.node)
        if self.conflict or args[args.index('--expected-etag') + 1] != self.node['etag']:
            raise workflow.WorkflowError('etag conflict')
        self.node['content'] = Path(args[args.index('--input') + 1]).read_text()
        self.node['metadata_json'] = args[args.index('--metadata-json') + 1]
        self.node['etag'] = 'v2'
        return {'node': {'path': self.node['path'], 'etag': 'v2'}, 'created': False}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / '.kinic-superpowers.json'
        self.config.write_text(json.dumps({
            'version': 1, 'database_id': 'db-test',
            'artifacts': {'spec': {'path': '/Knowledge/work/spec.md', 'local': 'docs/spec.md'}}
        }))
        self.cli = FakeCLI()
        self.work = workflow.Workspace(self.config, self.cli)

    def local(self):
        return self.root / 'docs/spec.md'

    def test_pull_and_push_preserve_metadata_and_bind_etag(self):
        self.work.pull('spec')
        self.assertEqual(self.local().read_text(), 'approved spec')
        self.local().write_text('updated spec')
        self.work.push('spec')
        self.assertEqual(self.cli.node['content'], 'updated spec')
        self.assertEqual(self.cli.node['metadata_json'], '{"owner":"team"}')
        self.assertIn('--expected-etag', self.cli.calls[-1])
        self.assertIn('v1', self.cli.calls[-1])

    def test_push_requires_pull(self):
        self.local().parent.mkdir()
        self.local().write_text('blind overwrite')
        with self.assertRaises(workflow.WorkflowError):
            self.work.push('spec')
        self.assertEqual(self.cli.calls, [])

    def test_stale_etag_is_rejected_without_updating_baseline(self):
        self.work.pull('spec')
        self.local().write_text('my changes')
        self.cli.conflict = True
        with self.assertRaises(workflow.WorkflowError):
            self.work.push('spec')
        self.assertEqual(self.work.status('spec')['etag'], 'v1')
        self.assertEqual(self.local().read_text(), 'my changes')

    def test_pull_refuses_to_destroy_unpublished_work(self):
        self.work.pull('spec')
        self.local().write_text('unfinished')
        self.cli.node.update(content='someone else', etag='v9')
        with self.assertRaises(workflow.WorkflowError):
            self.work.pull('spec')
        self.assertEqual(self.local().read_text(), 'unfinished')

    def test_existing_untracked_file_is_not_overwritten(self):
        self.local().parent.mkdir()
        self.local().write_text('original user work')
        with self.assertRaises(workflow.WorkflowError):
            self.work.pull('spec')

    def test_restarted_session_recovers_remote_document(self):
        self.work.pull('spec')
        self.cli.node.update(content='Task 1: complete; Task 2: next', etag='v9')
        restarted = workflow.Workspace(self.config, self.cli)
        restarted.pull('spec')
        self.assertEqual(self.local().read_text(), 'Task 1: complete; Task 2: next')
        self.assertEqual(restarted.status('spec')['etag'], 'v9')

    def test_mapping_change_invalidates_snapshot(self):
        self.work.pull('spec')
        cfg = json.loads(self.config.read_text())
        cfg['database_id'] = 'other-db'
        self.config.write_text(json.dumps(cfg))
        with self.assertRaises(workflow.WorkflowError):
            workflow.Workspace(self.config, self.cli).push('spec')

    def test_rejects_local_traversal_and_symlink_escape(self):
        cfg = json.loads(self.config.read_text())
        cfg['artifacts']['spec']['local'] = '../outside.md'
        self.config.write_text(json.dumps(cfg))
        with self.assertRaises(workflow.WorkflowError):
            workflow.Workspace(self.config, self.cli)

    def test_symlink_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / 'docs').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(workflow.WorkflowError):
                self.work.pull('spec')

    def test_missing_etag_does_not_write_local_file(self):
        self.cli.node['etag'] = ''
        with self.assertRaises(workflow.WorkflowError):
            self.work.pull('spec')
        self.assertFalse(self.local().exists())

    def test_ambiguous_ack_keeps_previous_baseline(self):
        self.work.pull('spec')
        self.local().write_text('possibly committed')
        self.work.run = lambda args: {'created': False}
        with self.assertRaises(workflow.WorkflowError):
            self.work.push('spec')
        self.assertEqual(self.work.status('spec')['etag'], 'v1')
        self.assertTrue(self.work.status('spec')['dirty'])

    def test_status_does_not_claim_remote_freshness(self):
        self.work.pull('spec')
        count = len(self.cli.calls)
        self.assertFalse(self.work.status('spec')['remote_checked'])
        self.assertEqual(len(self.cli.calls), count)

    def test_unchanged_push_checks_remote_revision(self):
        self.work.pull('spec')
        self.cli.node.update(content='changed elsewhere', etag='v8')
        with self.assertRaises(workflow.WorkflowError):
            self.work.push('spec')
        self.assertEqual(self.work.status('spec')['etag'], 'v1')

    def test_real_subprocess_transport_round_trip(self):
        fake = self.root / 'fake cli'
        state = self.root / 'server.json'
        state.write_text(json.dumps(self.cli.node))
        fake.write_text('''#!/usr/bin/env python3
import json, sys
from pathlib import Path
state = Path(__file__).with_name('server.json')
args = sys.argv[1:]
node = json.loads(state.read_text())
if 'read-node' in args:
    print(json.dumps(node))
else:
    if args[args.index('--expected-etag') + 1] != node['etag']:
        print('etag mismatch', file=sys.stderr)
        sys.exit(1)
    node['content'] = Path(args[args.index('--input') + 1]).read_text()
    node['etag'] = 'subprocess-v2'
    state.write_text(json.dumps(node))
    print(json.dumps({'node': {'path': node['path'], 'etag': node['etag']}, 'created': False}))
''')
        fake.chmod(0o700)
        work = workflow.Workspace(self.config, workflow.CLI(str(fake), self.root))
        work.pull('spec')
        self.local().write_text('transport round trip')
        work.push('spec')
        restarted = workflow.Workspace(self.config, workflow.CLI(str(fake), self.root))
        restarted.pull('spec')
        self.assertEqual(self.local().read_text(), 'transport round trip')
        self.assertEqual(restarted.status('spec')['etag'], 'subprocess-v2')

    def test_wrong_remote_path_does_not_write_local_file(self):
        self.cli.node['path'] = '/wrong'
        with self.assertRaises(workflow.WorkflowError):
            self.work.pull('spec')
        self.assertFalse(self.local().exists())

    def test_unknown_role_fails_before_transport(self):
        with self.assertRaises(workflow.WorkflowError):
            self.work.pull('unknown')
        self.assertEqual(self.cli.calls, [])


class TransportTests(unittest.TestCase):
    def test_non_ii_identity_is_explicit_opt_in(self):
        with patch.object(workflow.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout='{}')
            workflow.CLI('/custom/kinic', allow_non_ii_identity=True)(['status', '--json'])
            self.assertEqual(run.call_args.args[0],
                             ['/custom/kinic', '--allow-non-ii-identity', 'status', '--json'])

    def test_uses_argv_without_shell_and_pins_cwd(self):
        args = ['--database-id', 'db $(touch never)', 'read-node', '--path', '/x; echo nope']
        with patch.object(workflow.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess(args, 0, stdout='{}')
            self.assertEqual(workflow.CLI(cwd='/project')(args), {})
            positional, keywords = run.call_args
            self.assertEqual(positional[0], ['kinic-vfs-cli', *args])
            self.assertNotIn('shell', keywords)
            self.assertEqual(keywords['cwd'], '/project')

    def test_nonzero_and_invalid_json_fail(self):
        for result in [subprocess.CompletedProcess([], 1, stdout='', stderr='offline'),
                       subprocess.CompletedProcess([], 0, stdout='not json')]:
            with patch.object(workflow.subprocess, 'run', return_value=result):
                with self.assertRaises(workflow.WorkflowError):
                    workflow.CLI()([])

    def test_timeout_does_not_succeed(self):
        with patch.object(workflow.subprocess, 'run', side_effect=subprocess.TimeoutExpired('cli', 60)):
            with self.assertRaises(workflow.WorkflowError):
                workflow.CLI()([])


if __name__ == '__main__':
    unittest.main()
