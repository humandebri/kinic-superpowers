"""Project/workflow contracts against an in-memory CLI."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('kinic_project', Path(__file__).resolve().parents[2] / 'scripts/kinic_project.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class Fake:
    def __init__(self):
        self.nodes = {}
        self.principal = 'principal-a'
        self.fail = None
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if 'show' in args and 'identity' in args:
            return {'principal': self.principal}
        if 'database' in args and 'list' in args:
            return [{'database_id': 'db', 'name': 'Test wiki', 'role': 'writer', 'status': 'active'}]
        if 'database' in args:
            return {'canister_id': 'canister', 'replica_host': 'https://icp-api.io'}
        if 'status' in args:
            return {'ok': True}
        path = args[args.index('--path') + 1] if '--path' in args else None
        if 'read-node' in args:
            if path not in self.nodes:
                raise p.ProjectError('error: node not found: ' + path)
            return dict(self.nodes[path])
        if 'list-children' in args:
            return [dict(n) for k, n in self.nodes.items() if str(Path(k).parent) == path]
        if self.fail and self.fail in path:
            raise p.ProjectError('network unavailable')
        if 'mkdir-node' in args:
            self.nodes[path] = {'path': path, 'kind': 'folder', 'content': '', 'metadata_json': '{}', 'etag': '1'}
        elif 'write-node' in args:
            self.nodes[path] = {'path': path, 'kind': 'file', 'content': Path(args[args.index('--input') + 1]).read_text(), 'metadata_json': args[args.index('--metadata-json') + 1], 'etag': str(len(self.calls))}
        return {'node': self.nodes[path]}


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = Fake()
        p.initialize(self.root, 'db', '/Knowledge/tests', allow_non_ii_identity=True, run=self.fake)
        self.project = p.Project(self.root, run=self.fake)

    def test_new_ready_and_sessions_are_isolated(self):
        a, b = self.project.new('A'), self.project.new('B')
        self.project.use(a['id'], 'chat-a')
        self.project.use(b['id'], 'chat-b')
        self.assertEqual(self.project.resolve('chat-a')['id'], a['id'])
        self.assertEqual(self.project.resolve('chat-b')['id'], b['id'])
        with self.assertRaises(p.ProjectError):
            self.project.resolve('chat-a', b['id'])
        with self.assertRaises(p.ProjectError):
            self.project.resolve()
        self.assertEqual(len(self.project.list()), 2)

    def test_partial_resume_preserves_owned_content(self):
        self.fake.fail = '/plan.md'
        with self.assertRaises(p.ProjectError):
            self.project.new('partial')
        record = json.loads(next((self.root / '.superpowers/kinic-project/journals').glob('*.json')).read_text())
        target = record['artifacts']['spec']['path']
        self.fake.nodes[target]['content'] = 'human edits'
        self.fake.fail = None
        result = self.project.new(resume=record['id'])
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(self.fake.nodes[target]['content'], 'human edits')

    def test_foreign_content_is_never_replaced(self):
        self.fake.fail = '/plan.md'
        with self.assertRaises(p.ProjectError):
            self.project.new('partial')
        record = json.loads(next((self.root / '.superpowers/kinic-project/journals').glob('*.json')).read_text())
        self.fake.fail = None
        path = record['artifacts']['plan']['path']
        self.fake.nodes[path] = {'path': path, 'kind': 'file', 'content': 'foreign', 'metadata_json': '{}', 'etag': 'x'}
        with self.assertRaisesRegex(p.ProjectError, 'foreign'):
            self.project.new(resume=record['id'])
        self.assertEqual(self.fake.nodes[path]['content'], 'foreign')

    def test_changed_identity_fails_before_read(self):
        self.fake.principal = 'principal-b'
        with self.assertRaisesRegex(p.ProjectError, 'principal'):
            self.project.list()

    def test_readonly_local_resolution(self):
        a = self.project.new('A')
        self.project.use(a['id'], 'session')
        before = len(self.fake.calls)
        self.assertEqual(self.project.resolve('session', remote=False)['id'], a['id'])
        self.assertEqual(len(self.fake.calls), before)

    def test_init_idempotent_and_refuses_retarget(self):
        self.assertEqual(p.initialize(self.root, 'db', '/Knowledge/tests', run=self.fake)['version'], 2)
        with self.assertRaises(p.ProjectError):
            p.initialize(self.root, 'different', '/Knowledge/tests', run=self.fake)

    def setup_root(self):
        root = self.root / 'new-project'
        root.mkdir()
        (root / '.git').mkdir()
        return root

    def discovery_transport(self, linked=None, databases=()):
        def run(args):
            if 'database' in args and 'current' in args:
                return {'database_id': linked, 'canister_id': 'canister', 'replica_host': 'https://icp-api.io'}
            if 'database' in args and 'list' in args:
                return list(databases)
            return self.fake(args)
        return run

    def test_init_uses_linked_database_and_automatic_project_scope(self):
        root = self.setup_root()
        config = p.initialize(root, run=self.discovery_transport(linked='db-linked', databases=[
            {'database_id': 'db-linked', 'name': 'Linked wiki', 'role': 'writer', 'status': 'active'}]))
        self.assertEqual(config['database_id'], 'db-linked')
        self.assertTrue(config['scope'].startswith('/Knowledge/projects/new-project-'))
        self.assertTrue(any('status' in args and 'db-linked' in args for args in self.fake.calls))

    def test_first_init_in_git_worktree_shares_config_and_keeps_state_local(self):
        main = self.root / 'git-project'
        tree = main / '.worktrees/test'
        main.mkdir()
        def git(cwd, *args):
            return subprocess.run(['git', '-c', 'commit.gpgsign=false',
                '-c', 'user.name=Kinic test', '-c', 'user.email=test@example.invalid', *args],
                cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
        git(main, 'init', '-q', '-b', 'main')
        git(main, 'commit', '-q', '--allow-empty', '-m', 'test fixture')
        git(main, 'worktree', 'add', '-q', '--detach', str(tree), 'HEAD')
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        proposal = p.initialize(tree, inspect=True, run=self.fake)
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()})
        config = p.initialize(tree, run=self.fake)
        self.assertEqual(config['scope'], proposal['scope'])
        self.assertTrue(config['scope'].startswith('/Knowledge/projects/git-project-'))
        self.assertTrue((main / '.kinic-superpowers.json').is_file())
        self.assertFalse((tree / '.kinic-superpowers.json').exists())
        primary = p.Project(main, run=self.fake)
        child = p.Project(tree, run=self.fake)
        self.assertEqual(primary.config_path, child.config_path)
        self.assertEqual(p.initialize(main, run=self.fake), config)
        self.assertEqual(git(main, 'check-ignore', '.kinic-superpowers.json'), '.kinic-superpowers.json')
        self.assertEqual(git(tree, 'check-ignore', '.superpowers/test'), '.superpowers/test')
        case = child.new('Shared project')
        child.use(case['id'], 'same-chat')
        with self.assertRaisesRegex(p.ProjectError, 'no workflow selected'):
            primary.resolve('same-chat')

    def test_linked_unwritable_database_is_rejected_before_saving(self):
        root = self.setup_root()
        for changes in ({'role': 'reader'}, {'cycles_suspended_at_ms': 1}, {'status': 'deleted'}):
            with self.subTest(changes=changes):
                databases = [{'database_id': 'db-linked', 'name': 'Linked wiki', 'role': 'writer', 'status': 'active'}]
                databases[0].update(changes)
                databases.append({'database_id': 'db-other', 'name': 'Writable wiki', 'role': 'writer', 'status': 'active'})
                run = self.discovery_transport(linked='db-linked', databases=databases)
                for inspect in (True, False):
                    with self.assertRaisesRegex(p.ProjectError, 'not writable'):
                        p.initialize(root, inspect=inspect, run=run)
                self.assertFalse((root / '.kinic-superpowers.json').exists())
                self.assertFalse((root / '.gitignore').exists())

    def test_saved_database_with_revoked_write_access_is_rejected_without_changes(self):
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        run = self.discovery_transport(databases=[
            {'database_id': 'db', 'name': 'Test wiki', 'role': 'reader', 'status': 'active'}])
        for inspect in (True, False):
            with self.assertRaisesRegex(p.ProjectError, 'not writable'):
                p.initialize(self.root, inspect=inspect, run=run)
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()})

    def test_init_selects_only_active_writable_database(self):
        root = self.setup_root()
        databases = [
            {'database_id': 'db-readable', 'name': 'Read only', 'role': 'reader', 'status': 'active'},
            {'database_id': 'db-suspended', 'name': 'Suspended', 'role': 'owner', 'status': 'active', 'cycles_suspended_at_ms': 1},
            {'database_id': 'db-writable', 'name': 'Memo', 'role': 'writer', 'status': 'active'}]
        config = p.initialize(root, run=self.discovery_transport(databases=databases))
        self.assertEqual(config['database_id'], 'db-writable')

    def test_inspect_shows_named_choices_without_saving_or_creating_pages(self):
        root = self.setup_root()
        databases = [{'database_id': 'db-a', 'name': 'Memo', 'role': 'writer', 'status': 'active'},
                     {'database_id': 'db-b', 'name': 'Work', 'role': 'owner', 'status': 'active'}]
        run = self.discovery_transport(databases=databases)
        before = list(root.iterdir())
        proposal = p.initialize(root, inspect=True, run=run)
        self.assertTrue(proposal['selection_required'])
        self.assertEqual([item['name'] for item in proposal['database_candidates']], ['Memo', 'Work'])
        self.assertEqual(list(root.iterdir()), before)
        with self.assertRaisesRegex(p.ProjectError, 'Memo'):
            p.initialize(root, run=run)
        self.assertFalse((root / '.kinic-superpowers.json').exists())
        self.assertFalse(any('write-node' in args or 'mkdir-node' in args for args in self.fake.calls))

    def test_init_omitted_arguments_reuse_saved_settings(self):
        config = p.initialize(self.root, run=self.fake)
        self.assertEqual(config, self.project.config)

    def test_inspecting_existing_config_never_repairs_or_migrates_it(self):
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        proposal = p.initialize(self.root, inspect=True, run=self.fake)
        self.assertEqual(proposal['database_id'], 'db')
        self.assertEqual(proposal['database_name'], 'Test wiki')
        after = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_auth_failure_never_means_missing(self):
        def fail(args):
            if 'read-node' in args:
                raise p.ProjectError('permission denied: not found')
            return self.fake(args)
        project = p.Project(self.root, run=fail)
        with self.assertRaisesRegex(p.ProjectError, 'permission denied'):
            project.new('x')
        self.assertFalse(any('write-node' in c for c in self.fake.calls))

    def test_explicit_config_override_uses_current_workspace(self):
        other = self.root / 'other'
        other.mkdir()
        project = p.Project(other, config_path=self.project.config_path, run=self.fake)
        self.assertEqual(project.root, other.resolve())
        self.assertEqual(project.config_path, self.project.config_path)

    def test_legacy_init_preserves_config(self):
        self.project.config_path.write_text('{"version": 1, "database_id": "db", "artifacts": {}}')
        before = self.project.config_path.read_text()
        with self.assertRaisesRegex(p.ProjectError, 'version 1'):
            p.initialize(self.root, 'db', '/Knowledge/tests', run=self.fake)
        self.assertEqual(self.project.config_path.read_text(), before)

    def test_migration_preserves_source_and_uses_remote_manifest(self):
        legacy = {'version': 1, 'database_id': 'db', 'artifacts': {'spec': {'path': '/Knowledge/old.md', 'local': 'docs/old.md'}}}
        self.project.config_path.write_text(json.dumps(legacy))
        self.fake.nodes['/Knowledge/old.md'] = {'path': '/Knowledge/old.md', 'kind': 'file', 'content': 'approved original', 'etag': 'old-etag', 'metadata_json': '{}'}
        config = p.initialize(self.root, 'db', '/Knowledge/tests', allow_non_ii_identity=True, migrate=True, run=self.fake)
        project = p.Project(self.root, run=self.fake)
        manifest = project.resolve(workflow_id=config['legacy_workflow_id'])
        self.assertTrue(manifest['legacy'])
        self.assertEqual(project.workspace_data(manifest)['artifacts'], legacy['artifacts'])
        self.assertEqual(self.fake.nodes['/Knowledge/old.md']['content'], 'approved original')
        self.assertEqual(json.loads(self.project.config_path.with_name('.kinic-superpowers.json.v1-backup').read_text()), legacy)

    def test_uncertain_write_acknowledgement_recovers_without_overwrite(self):
        seen = []
        def uncertain(args):
            result = self.fake(args)
            if 'write-node' in args and '/spec.md' in args[args.index('--path') + 1] and not seen:
                seen.append(True)
                raise p.ProjectError('timeout after writing')
            return result
        project = p.Project(self.root, run=uncertain)
        manifest = project.new('uncertain')
        self.assertEqual(manifest['state'], 'ready')
        spec_writes = [c for c in self.fake.calls if 'write-node' in c and c[c.index('--path') + 1].endswith('/spec.md')]
        self.assertEqual(len(spec_writes), 1)

    def test_worktree_shares_config_but_separates_bindings_and_copies(self):
        main = self.root / 'main'
        child = self.root / 'child'
        (main / '.git/worktrees/child').mkdir(parents=True)
        child.mkdir()
        (child / '.git').write_text('gitdir: ' + str(main / '.git/worktrees/child'))
        (main / '.git/worktrees/child/commondir').write_text('../..')
        (main / '.kinic-superpowers.json').write_text(self.project.config_path.read_text())
        (main / '.git').is_dir()
        a = p.Project(main, run=self.fake)
        b = p.Project(child, run=self.fake)
        self.assertEqual(a.config_path, b.config_path)
        manifest = a.new('worktree')
        a.use(manifest['id'], 'same-session')
        with self.assertRaises(p.ProjectError):
            b.resolve('same-session')
        b.use(manifest['id'], 'same-session')
        self.assertNotEqual(a._binding_path('same-session'), b._binding_path('same-session'))
        self.assertNotEqual(a.root / a.workspace_data(manifest)['artifacts']['spec']['local'], b.root / b.workspace_data(manifest)['artifacts']['spec']['local'])

    def test_init_failure_does_not_save_connection(self):
        isolated = self.root / 'isolated'
        isolated.mkdir()
        def denied(args):
            if 'status' in args:
                raise p.ProjectError('not authorized')
            return self.fake(args)
        with self.assertRaises(p.ProjectError):
            p.initialize(isolated, 'db', '/Knowledge/tests', run=denied, config_path=isolated / '.kinic-superpowers.json')
        self.assertFalse((isolated / '.kinic-superpowers.json').exists())

    def test_migration_retry_after_partial_remote_failure(self):
        legacy = {'version': 1, 'database_id': 'db', 'artifacts': {'spec': {'path': '/Knowledge/old.md', 'local': 'docs/old.md'}}}
        self.project.config_path.write_text(json.dumps(legacy))
        self.fake.fail = '/manifest.json'
        with self.assertRaisesRegex(p.ProjectError, 'workflow new --resume'):
            p.initialize(self.root, 'db', '/Knowledge/tests', allow_non_ii_identity=True, migrate=True, run=self.fake)
        self.fake.fail = None
        self.fake.nodes['/Knowledge/old.md'] = {'path': '/Knowledge/old.md', 'kind': 'file', 'content': 'kept', 'etag': 'x', 'metadata_json': '{}'}
        config = p.initialize(self.root, 'db', '/Knowledge/tests', migrate=True, run=self.fake)
        manifest = p.Project(self.root, run=self.fake).resolve(workflow_id=config['legacy_workflow_id'])
        self.assertEqual(manifest['state'], 'ready')

    def test_migration_can_recover_in_another_checkout_without_local_journal(self):
        legacy = {'version': 1, 'database_id': 'db', 'artifacts': {
            'spec': {'path': '/Knowledge/old.md', 'local': 'docs/old.md'}}}
        self.project.config_path.write_text(json.dumps(legacy))
        self.fake.nodes['/Knowledge/old.md'] = {'path': '/Knowledge/old.md', 'kind': 'file',
            'content': 'approved original', 'etag': 'old-etag', 'metadata_json': '{}'}
        config = p.initialize(self.root, 'db', '/Knowledge/tests', migrate=True, run=self.fake)
        original_nodes = json.loads(json.dumps(self.fake.nodes))
        other = self.root / 'other'
        other.mkdir()
        recovered = p.initialize(other, 'db', '/Knowledge/tests',
                                 config_path=self.project.config_path, run=self.fake)
        self.assertEqual(recovered, config)
        self.assertEqual(self.fake.nodes, original_nodes)
        project = p.Project(other, config_path=self.project.config_path, run=self.fake)
        self.assertEqual(project.resolve(workflow_id=config['legacy_workflow_id'])['state'], 'ready')

    def test_relative_cli_path_is_reusable_from_another_checkout(self):
        isolated = self.root / 'relative-cli'
        isolated.mkdir()
        executable = isolated / 'kinic'
        executable.write_text(f'#!{sys.executable}\nimport json, sys\n'
            'if "show" in sys.argv: print(json.dumps({"principal": "principal-a"}))\n'
            'elif "current" in sys.argv: print(json.dumps({"canister_id": "canister", "replica_host": "https://example.invalid"}))\n'
            'elif "list" in sys.argv: print(json.dumps([{"database_id": "db", "name": "Test wiki", "role": "writer", "status": "active"}]))\n'
            'else: print("{}")\n')
        executable.chmod(0o755)
        config = p.initialize(isolated, 'db', '/Knowledge/tests',
                              cli_path=os.path.relpath(executable),
                              config_path=isolated / '.kinic-superpowers.json')
        self.assertEqual(config['cli'], str(executable.resolve()))
        other = self.root / 'other'
        other.mkdir()
        project = p.Project(other, config_path=isolated / '.kinic-superpowers.json')
        project._validate_identity()

    def test_incomplete_migration_resumes_from_remote_in_another_checkout(self):
        legacy = {'version': 1, 'database_id': 'db', 'artifacts': {
            'spec': {'path': '/Knowledge/old.md', 'local': 'docs/old.md'}}}
        self.project.config_path.write_text(json.dumps(legacy))
        with self.assertRaisesRegex(p.ProjectError, 'legacy artifact missing'):
            p.initialize(self.root, 'db', '/Knowledge/tests', migrate=True, run=self.fake)
        config = json.loads(self.project.config_path.read_text())
        manifest_path = self.project._manifest_path(config['legacy_workflow_id'])
        original_nonce = json.loads(self.fake.nodes[manifest_path]['content'])['nonce']
        self.fake.nodes['/Knowledge/old.md'] = {'path': '/Knowledge/old.md', 'kind': 'file',
            'content': 'approved original', 'etag': 'old-etag', 'metadata_json': '{}'}
        other = self.root / 'other'
        other.mkdir()
        p.initialize(other, 'db', '/Knowledge/tests', config_path=self.project.config_path, run=self.fake)
        record = json.loads(self.fake.nodes[manifest_path]['content'])
        self.assertEqual(record['state'], 'ready')
        self.assertEqual(record['nonce'], original_nonce)
        self.assertEqual(self.fake.nodes['/Knowledge/old.md']['etag'], 'old-etag')

    def test_recovered_migration_rejects_foreign_manifest_before_saving_journal(self):
        legacy = {'version': 1, 'database_id': 'db', 'artifacts': {
            'spec': {'path': '/Knowledge/old.md', 'local': 'docs/old.md'}}}
        self.project.config_path.write_text(json.dumps(legacy))
        self.fake.nodes['/Knowledge/old.md'] = {'path': '/Knowledge/old.md', 'kind': 'file',
            'content': 'approved original', 'etag': 'old-etag', 'metadata_json': '{}'}
        config = p.initialize(self.root, 'db', '/Knowledge/tests', migrate=True, run=self.fake)
        self.fake.nodes[self.project._manifest_path(config['legacy_workflow_id'])]['metadata_json'] = '{}'
        original_nodes = json.loads(json.dumps(self.fake.nodes))
        other = self.root / 'other'
        other.mkdir()
        with self.assertRaisesRegex(p.ProjectError, 'foreign node collision'):
            p.initialize(other, 'db', '/Knowledge/tests', config_path=self.project.config_path, run=self.fake)
        self.assertFalse((other / '.superpowers/kinic-project/journals').exists())
        self.assertEqual(self.fake.nodes, original_nodes)

    def test_scope_change_invalidates_old_session_binding(self):
        a = self.project.new('A')
        self.project.use(a['id'], 'session')
        config = json.loads(self.project.config_path.read_text())
        config['scope'] = '/Knowledge/elsewhere'
        self.project.config_path.write_text(json.dumps(config))
        with self.assertRaisesRegex(p.ProjectError, 'another connection'):
            p.Project(self.root, run=self.fake).resolve('session', remote=False)

    def test_remote_resolution_does_not_change_local_bytes_or_mtime(self):
        manifest = self.project.new('A')
        self.project.use(manifest['id'], 'session')
        def snapshot():
            return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns) for path in self.root.rglob('*') if path.is_file()}
        before = snapshot()
        self.project.resolve('session')
        self.assertEqual(snapshot(), before)

    def test_corrupt_resume_journal_rejected_before_remote_io(self):
        self.fake.fail = '/plan.md'
        with self.assertRaises(p.ProjectError):
            self.project.new('partial')
        journal = next((self.root / '.superpowers/kinic-project/journals').glob('*.json'))
        original = json.loads(journal.read_text())
        for mutate in (lambda r: r.update(id='00000000-0000-4000-8000-000000000001'),
                       lambda r: r['artifacts']['spec'].update(path='/Knowledge/foreign.md'),
                       lambda r: r['artifacts'].update(extra={'path': '/Knowledge/foreign.md', 'local': 'foreign.md'}),
                       lambda r: r.update(nonce=''),
                       lambda r: r.update(state='unknown')):
            record = json.loads(json.dumps(original))
            mutate(record)
            journal.write_text(json.dumps(record))
            before = len(self.fake.calls)
            with self.assertRaises(p.ProjectError):
                self.project.new(resume=original['id'])
            self.assertEqual(len(self.fake.calls), before)

    def test_cache_swap_rejected_in_local_resolution(self):
        a, b = self.project.new('A'), self.project.new('B')
        cache = self.project.directory / 'manifests' / (a['id'] + '.json')
        cache.write_text(json.dumps(b))
        with self.assertRaisesRegex(p.ProjectError, 'id mismatch'):
            self.project.resolve(workflow_id=a['id'], remote=False)

    def test_state_symlink_escape_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        target = self.project.directory
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(p.ProjectError, 'symlink'):
            self.project.new('escape')
        self.assertEqual(list(outside.iterdir()), [])

    def test_binding_and_cache_file_symlinks_rejected(self):
        a = self.project.new('A')
        self.project.use(a['id'], 'session')
        outside = self.root / 'outside.json'
        outside.write_text('{}')
        for target in (self.project._binding_path('session'), self.project.directory / 'manifests' / (a['id'] + '.json')):
            before = target.read_text()
            target.unlink()
            target.symlink_to(outside)
            with self.assertRaisesRegex(p.ProjectError, 'symlink'):
                self.project.resolve('session', remote=False)
            target.unlink()
            target.write_text(before)
        self.assertEqual(outside.read_text(), '{}')

    def test_migration_failure_still_ignores_local_state(self):
        self.project.config_path.write_text(json.dumps({'version': 1, 'database_id': 'db', 'artifacts': {'spec': {'path': '/Knowledge/old.md', 'local': 'docs/old.md'}}}))
        (self.root / '.gitignore').unlink()
        self.fake.fail = '/manifest.json'
        with self.assertRaises(p.ProjectError):
            p.initialize(self.root, 'db', '/Knowledge/tests', migrate=True, run=self.fake)
        self.assertIn('.superpowers/', (self.root / '.gitignore').read_text().splitlines())
        self.assertIn('.kinic-superpowers.json.v1-backup', (self.root / '.gitignore').read_text().splitlines())

    def test_corrupt_connection_config_never_uses_ambient_cli_defaults(self):
        original = json.loads(self.project.config_path.read_text())
        cases = [(key, value) for key in ('canister_id', 'replica_host', 'database_id', 'cli') for value in (None, '', '   ', False)]
        cases += [('identity.principal', value) for value in (None, '', '   ', False)]
        cases += [('identity.allow_non_ii_identity', value) for value in (None, '', 'true', 1)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                config = json.loads(json.dumps(original))
                if key.startswith('identity.'):
                    config['identity'][key.split('.')[1]] = value
                else:
                    config[key] = value
                self.project.config_path.write_text(json.dumps(config))
                before = len(self.fake.calls)
                with self.assertRaises(p.ProjectError):
                    p.Project(self.root, run=self.fake)
                self.assertEqual(len(self.fake.calls), before)
        for key in ('canister_id', 'replica_host', 'database_id', 'cli', 'identity'):
            config = json.loads(json.dumps(original))
            del config[key]
            self.project.config_path.write_text(json.dumps(config))
            before = len(self.fake.calls)
            with self.assertRaises(p.ProjectError):
                p.initialize(self.root, 'db', '/Knowledge/tests', run=self.fake)
            self.assertEqual(len(self.fake.calls), before)
