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

    def workspace_files(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob('*') if path.is_file()}

    def test_check_reports_freshness_without_changing_files_or_remote(self):
        self.work.pull('spec')
        for local_content, remote_etag, expected in [
                ('approved spec', 'v1', 'clean'),
                ('my changes', 'v1', 'local_changed'),
                ('approved spec', 'v9', 'remote_changed'),
                ('my changes', 'v9', 'conflict')]:
            with self.subTest(state=expected):
                self.local().write_text(local_content)
                self.cli.node.update(content='remote content', etag=remote_etag)
                before = self.workspace_files()
                remote = dict(self.cli.node)
                count = len(self.cli.calls)
                result = self.work.check('spec')
                self.assertEqual(result['state'], expected)
                self.assertTrue(result['remote_checked'])
                self.assertEqual(result['etag'], 'v1')
                self.assertEqual(result['remote_etag'], remote_etag)
                self.assertEqual(result['dirty'], local_content != 'approved spec')
                self.assertEqual(self.workspace_files(), before)
                self.assertEqual(self.cli.node, remote)
                self.assertEqual(self.cli.calls[count:], [
                    ['--database-id', 'db-test', 'read-node',
                     '--path', '/Knowledge/work/spec.md', '--json']])

    def test_check_without_baseline_is_untracked_with_or_without_local(self):
        for content in [None, 'untracked work']:
            with self.subTest(local_content=content):
                if content is not None:
                    self.local().parent.mkdir()
                    self.local().write_text(content)
                before = self.workspace_files()
                result = self.work.check('spec')
                self.assertEqual(result['state'], 'untracked')
                self.assertIsNone(result['etag'])
                self.assertIsNone(result['dirty'])
                self.assertTrue(result['remote_checked'])
                self.assertEqual(self.workspace_files(), before)
                self.assertFalse((self.root / '.superpowers').exists())

    def test_check_missing_local_preserves_baseline(self):
        self.work.pull('spec')
        self.local().unlink()
        self.cli.node['etag'] = 'v9'
        before = self.workspace_files()
        result = self.work.check('spec')
        self.assertEqual(result['state'], 'missing_local')
        self.assertIsNone(result['dirty'])
        self.assertTrue(result['remote_checked'])
        self.assertEqual(self.workspace_files(), before)
        self.assertFalse(self.local().exists())

    def test_check_unknown_role_fails_before_transport(self):
        with self.assertRaises(workflow.WorkflowError):
            self.work.check('unknown')
        self.assertEqual(self.cli.calls, [])

    def test_check_rejects_malformed_remote_without_changing_files(self):
        self.work.pull('spec')
        before = self.workspace_files()
        valid = dict(self.cli.node)
        malformed = [None, [], {}, *[
            {**valid, field: value} for field, values in [
                ('path', ['/wrong', None]), ('kind', ['directory', None]),
                ('content', [None, 42]), ('etag', ['', None, 42]),
                ('metadata_json', [None, {}])]
            for value in values]]
        for node in malformed:
            with self.subTest(node=node):
                self.work.run = lambda args: node
                with self.assertRaises(workflow.WorkflowError):
                    self.work.check('spec')
                self.assertEqual(self.workspace_files(), before)
                self.assertFalse(self.work.status('spec')['remote_checked'])

    def test_check_transport_failure_preserves_local_and_baseline(self):
        self.work.pull('spec')
        self.local().write_text('unpublished')
        before = self.workspace_files()

        def offline(args):
            raise workflow.WorkflowError('offline')

        self.work.run = offline
        with self.assertRaisesRegex(workflow.WorkflowError, 'offline'):
            self.work.check('spec')
        self.assertEqual(self.workspace_files(), before)
        self.assertFalse(self.work.status('spec')['remote_checked'])

    def test_check_cli_selects_role_and_aggregates_all_roles(self):
        self.work.pull('spec')
        cfg = json.loads(self.config.read_text())
        cfg['artifacts']['plan'] = {'path': '/Knowledge/work/plan.md', 'local': 'docs/plan.md'}
        self.config.write_text(json.dumps(cfg))
        fake = self.root / 'fake check cli'
        fake.write_text('''#!/usr/bin/env python3
import json, sys
from pathlib import Path
args = sys.argv[1:]
if 'read-node' not in args:
    sys.exit(3)
path = args[args.index('--path') + 1]
nodes = json.loads(Path(__file__).with_name('server.json').read_text())
print(json.dumps(nodes[path]))
''')
        fake.chmod(0o700)
        state = self.root / 'server.json'
        plan = {**self.cli.node, 'path': '/Knowledge/work/plan.md'}
        nodes = {self.cli.node['path']: self.cli.node, plan['path']: plan}
        state.write_text(json.dumps(nodes))
        command = ['python3', str(SCRIPT), '--config', str(self.config), '--cli', str(fake)]

        def invoke(*args):
            return subprocess.run([*command, *args], capture_output=True, text=True, check=False)

        selected = invoke('check', 'spec')
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual([json.loads(line)['state'] for line in selected.stdout.splitlines()], ['clean'])
        batch = invoke('check')
        self.assertEqual(batch.returncode, 1, batch.stderr)
        self.assertEqual([(row['role'], row['state']) for row in map(json.loads, batch.stdout.splitlines())],
                         [('spec', 'clean'), ('plan', 'untracked')])
        self.assertEqual(invoke('pull', 'plan').returncode, 0)
        self.assertEqual(invoke('check').returncode, 0)
        nodes[plan['path']]['etag'] = 'remote-v2'
        state.write_text(json.dumps(nodes))
        changed = invoke('check')
        self.assertEqual(changed.returncode, 1)
        self.assertEqual([json.loads(line)['state'] for line in changed.stdout.splitlines()],
                         ['clean', 'remote_changed'])
        nodes[self.cli.node['path']]['etag'] = ''
        nodes[plan['path']]['etag'] = 'v1'
        state.write_text(json.dumps(nodes))
        partial_failure = invoke('check')
        self.assertEqual(partial_failure.returncode, 1)
        rows = list(map(json.loads, partial_failure.stdout.splitlines()))
        self.assertEqual([(row['role'], row['state']) for row in rows],
                         [('spec', 'error'), ('plan', 'clean')])
        self.assertFalse(rows[0]['remote_checked'])
        self.assertIn('error', rows[0])
        nodes[self.cli.node['path']]['etag'] = 'v1'
        nodes[plan['path']]['etag'] = ''
        state.write_text(json.dumps(nodes))
        failed = invoke('check', 'plan')
        self.assertEqual(failed.returncode, 1)
        failed_row = json.loads(failed.stdout)
        self.assertEqual(failed_row['state'], 'error')
        self.assertFalse(failed_row['remote_checked'])
        self.assertIn('matching path', failed_row['error'])
        fake.unlink()
        unknown = invoke('check', 'unknown')
        self.assertEqual(unknown.returncode, 1)
        self.assertIn('unknown artifact', unknown.stderr)
        self.assertNotIn('could not finish', unknown.stderr)

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
