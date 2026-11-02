"""Scope relocation preserves evidence and resumes guarded, non-atomic steps."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import kinic_project as p
import kinic_scope_migration as m
from test_project import Fake as BaseFake, p as fixture_p


class Fake(BaseFake):
    def __call__(self, args):
        try:
            result = super().__call__(args)
        except fixture_p.ProjectError as exc:
            raise p.ProjectError(str(exc)) from exc
        if 'list-children' in args:
            return [{k: v for k, v in n.items() if k != 'content'} for n in result]
        return result


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = Fake()
        self.old = '/Knowledge/projects/demo'
        self.new = '/Knowledge/demo'
        p.initialize(self.root, 'db', self.old, run=self.fake)
        self.project = p.Project(self.root, run=self.fake)
        from kinic_registry import register
        register(self.project)
        self.record = self.project.new('A real case')
        self.local = 'docs/superpowers/plans/2026-10-16-demo.md'
        file = self.root / self.local
        file.parent.mkdir(parents=True)
        file.write_text('Approved at ' + self.old + '/history.md, etag old.\n')
        self.record = self.project.document('plan', self.local, workflow_id=self.record['id'])
        self.project.use(self.record['id'], 'chat-a')
        self.project.use(self.record['id'], 'chat-b')
        self.project.index()
        self.source = copy.deepcopy(self.fake.nodes)

    def run_move(self, apply=True):
        return m.migrate(self.project, self.new, apply=apply)

    def test_inspect_then_move_preserves_documents_and_selection(self):
        before = copy.deepcopy(self.fake.nodes)
        result = self.run_move(False)
        self.assertFalse(result['applied'])
        self.assertEqual(before, self.fake.nodes)
        self.assertEqual(self.project.config['scope'], self.old)
        result = self.run_move()
        self.assertEqual(result['phase'], 'complete')
        for path, node in self.source.items():
            if path.endswith('/index.md') or path.endswith('/manifest.json') or not path.startswith(self.old + '/'):
                continue
            self.assertEqual(self.fake.nodes[path], node)
            self.assertEqual(self.fake.nodes[path.replace(self.old, self.new, 1)]['content'], node['content'])
        for chat in ('chat-a', 'chat-b'):
            self.assertEqual(self.project.resolve(chat)['id'], self.record['id'])
        self.assertEqual(self.run_move()['phase'], 'complete')

    def test_dirty_baseline_rekeys_without_changing_local(self):
        file = self.root / self.local
        file.write_text('unpublished edit')
        self.run_move()
        key = p._hash(json.dumps(['db', self.new + '/plans/2026-10-16-demo.md', self.local]))
        baseline = p._read(self.root / '.superpowers/kinic' / (key + '.json'))
        self.assertEqual(file.read_text(), 'unpublished edit')
        self.assertEqual(baseline['sha256'], p._hash(self.source[self.old + '/plans/2026-10-16-demo.md']['content']))
        self.assertEqual(baseline['etag'], self.fake.nodes[self.new + '/plans/2026-10-16-demo.md']['etag'])

    def test_stale_baseline_is_not_promoted(self):
        key = p._hash(json.dumps(['db', self.old + '/plans/2026-10-16-demo.md', self.local]))
        path = self.root / '.superpowers/kinic' / (key + '.json')
        baseline = p._read(path)
        p._save(path, {**baseline, 'etag': 'stale'})
        self.run_move()
        key = p._hash(json.dumps(['db', self.new + '/plans/2026-10-16-demo.md', self.local]))
        self.assertFalse((path.parent / (key + '.json')).exists())

    def test_foreign_collision_blocks_and_unrelated_child_survives(self):
        path = self.new + '/project.json'
        self.fake.nodes[path] = dict(self.source[self.old + '/project.json'], path=path)
        with self.assertRaisesRegex(p.ProjectError, 'collision'):
            self.run_move()
        self.assertEqual(self.project.config['scope'], self.old)

    def test_interrupt_copy_and_target_edit(self):
        self.fake.fail = self.new + '/plans/'
        with self.assertRaises(p.ProjectError):
            self.run_move()
        self.fake.fail = None
        copied = self.new + '/index.md'
        self.fake.nodes[copied]['etag'] = 'human-change'
        with self.assertRaisesRegex(p.ProjectError, 'changed'):
            self.run_move()
        self.assertEqual(self.project.config['scope'], self.old)

    def test_source_edit_during_copy_stops_cutover(self):
        original = m._copy
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            self.fake.nodes[self.old + '/plans/2026-10-16-demo.md']['etag'] = 'changed'
            return result
        with patch.object(m, '_copy', changed), self.assertRaisesRegex(p.ProjectError, 'source changed'):
            self.run_move()
        self.assertEqual(self.project.config['scope'], self.old)

    def test_local_and_redirect_interruptions_resume(self):
        original = m._save
        failed = False
        def interrupted(path, data):
            nonlocal failed
            original(path, data)
            if Path(path) == self.project.config_path and not failed:
                failed = True
                raise OSError('crash after config switch')
        with patch.object(m, '_save', interrupted), self.assertRaises(OSError):
            self.run_move()
        with self.assertRaisesRegex(p.ProjectError, 'migration'):
            p.Project(self.root, run=self.fake)
        self.project = p.Project(self.root, run=self.fake, allow_migration=True)
        self.assertEqual(self.run_move()['phase'], 'complete')

    def test_empty_folders_and_unrelated_destination_children(self):
        for path in (self.old + '/empty', self.new, self.new + '/e2e-check'):
            self.fake.nodes[path] = dict(path=path, kind='folder', content='', metadata_json='{}', etag='1')
        self.run_move()
        self.assertIn(self.new + '/empty', self.fake.nodes)
        self.assertIn(self.new + '/e2e-check', self.fake.nodes)

    def test_linked_worktree_bindings_and_dirty_content(self):
        import subprocess
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '--allow-empty', '-qm', 'initial'], check=True)
        linked = self.root / 'linked'
        subprocess.run(['git', '-C', str(self.root), 'worktree', 'add', '-q', '--detach', str(linked)], check=True)
        other = p.Project(linked, run=self.fake)
        other.use(self.record['id'], 'linked-chat')
        file = linked / self.local
        file.parent.mkdir(parents=True)
        file.write_text('worktree unpublished edits')
        # Run from the worktree: shared lock, journal and config remain primary.
        self.project = other
        self.run_move()
        self.assertEqual(other.resolve('linked-chat', remote=False)['id'], self.record['id'])
        self.assertEqual(file.read_text(), 'worktree unpublished edits')
        self.assertEqual(p.Project(self.root, run=self.fake).resolve('chat-a', remote=False)['id'], self.record['id'])

    def test_v1_artifacts_keep_ids_titles_local_paths_and_historical_text(self):
        from test_project import legacy_new
        record = legacy_new(self.project, 'Existing v1 case')
        source = copy.deepcopy(record)
        path = record['artifacts']['review']['path']
        self.fake.nodes[path]['content'] = 'Approval for ' + self.old + '/plan.md at etag 17'
        self.run_move()
        moved = self.project.resolve(workflow_id=record['id'])
        self.assertEqual(moved['title'], source['title'])
        self.assertEqual(moved['version'], 1)
        for role, item in source['artifacts'].items():
            self.assertEqual(moved['artifacts'][role]['local'], item['local'])
        self.assertEqual(self.fake.nodes[path]['content'], self.fake.nodes[path.replace(self.old, self.new, 1)]['content'])

    def test_lost_copy_and_redirect_acknowledgements_resume(self):
        original = m._write
        for failure_path in (self.new + '/plans/2026-10-16-demo.md', self.old + '/index.md'):
            def interrupted(project, path, payload, expected=None):
                original(project, path, payload, expected)
                if path == failure_path:
                    raise p.ProjectError('lost response')
            with patch.object(m, '_write', interrupted), self.assertRaises(p.ProjectError):
                self.run_move()
        self.assertEqual(self.run_move()['phase'], 'complete')

    def test_unrelated_scope_local_records_are_retained(self):
        path = self.root / '.superpowers/kinic/sessions/other.json'
        value = {'session_id': 'other', 'workflow_id': 'other-workflow', 'project_fingerprint': 'other-scope'}
        p._save(path, value)
        result = self.run_move()
        self.assertEqual(p._read(path), value)
        self.assertEqual(result['local_skipped'], 1)

    def test_custom_index_prose_is_not_rewritten(self):
        path = self.old + '/index.md'
        self.fake.nodes[path]['content'] = 'Approved ' + self.old + '/plan.md.\n[plan](' + self.old + '/plan.md)'
        self.fake.nodes[path]['metadata_json'] = '{}'
        self.run_move()
        self.assertEqual(self.fake.nodes[self.new + '/index.md']['content'], 'Approved ' + self.old + '/plan.md.\n[plan](' + self.new + '/plan.md)')

    def test_overlapping_scopes_rejected(self):
        for scope in (self.old, self.old + '/nested', '/Knowledge/projects'):
            with self.assertRaises(p.ProjectError):
                m.migrate(self.project, scope, apply=True)

    def test_inspection_does_not_create_or_modify_local_state(self):
        def tree():
            return {str(path.relative_to(self.root)): path.read_bytes() if path.is_file() else None for path in self.root.rglob('*')}
        before = tree()
        self.run_move(False)
        self.assertEqual(tree(), before)

    def test_cli_has_inspection_default_and_explicit_apply(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('scope_cli', Path(__file__).resolve().parents[2] / 'scripts/kinic-workflow.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for flag in ([], ['--apply']):
            args = module.argument_parser().parse_args(['project', 'migrate', '--scope', self.new, *flag])
            self.assertEqual(args.apply, bool(flag))
            self.assertEqual(args.scope, self.new)

    def test_malformed_listing_rejected(self):
        original = self.project.transport
        self.project.transport = lambda args: {'nodes': [], 'truncated': True} if 'list-children' in args else original(args)
        with self.assertRaises(p.ProjectError):
            self.run_move()


if __name__ == '__main__':
    unittest.main()
