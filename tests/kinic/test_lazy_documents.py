import json
from pathlib import Path
import unittest
import subprocess
import test_project
p = test_project.p


class LazyDocumentsTests(unittest.TestCase):
    setUp = test_project.ProjectTests.setUp
    def authored(self, name, body='# Design\n\nA meaningful requirement.\n'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return name

    def test_new_has_no_placeholder_documents(self):
        record = self.project.new('Small change')
        self.assertEqual(record['version'], 2)
        self.assertEqual(record['artifacts'], {})
        self.assertEqual([n['path'] for n in self.fake.nodes.values() if n['kind'] == 'file'], [self.project._manifest_path(record['id'])])

    def test_document_publishes_authored_upstream_path_and_retries(self):
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/specs/2026-10-16-feature-design.md')
        result = self.project.document('spec', local, workflow_id=record['id'])
        remote = '/Knowledge/tests/specs/2026-10-16-feature-design.md'
        self.assertEqual(result['artifacts']['spec'], {'local': local, 'path': remote})
        self.assertEqual(self.fake.nodes[remote]['content'], (self.root / local).read_text())
        self.assertEqual(self.project.document('spec', local, workflow_id=record['id']), result)

    def test_empty_document_rejected_before_creation(self):
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/specs/2026-10-16-empty-design.md', '# Heading\n')
        with self.assertRaisesRegex(p.ProjectError, 'authored'):
            self.project.document('spec', local, workflow_id=record['id'])
        self.assertEqual(self.project.resolve(workflow_id=record['id'])['artifacts'], {})

    def test_progress_requires_plan_identity(self):
        record = self.project.new('Feature')
        plan = self.authored('docs/superpowers/plans/2026-10-16-feature.md')
        progress = self.authored('.superpowers/sdd/2026-10-16-feature/progress.md', '# SDD ledger — plan: other.md\n\nTask 1: pending\n')
        self.project.document('plan', plan, workflow_id=record['id'])
        with self.assertRaisesRegex(p.ProjectError, 'ledger'):
            self.project.document('progress', progress, workflow_id=record['id'])
        self.authored(progress, '# SDD ledger — plan: '+plan+'\n\nTask 1: pending\n')
        result = self.project.document('progress', progress, workflow_id=record['id'])
        self.assertEqual(result['artifacts']['progress']['path'], '/Knowledge/tests/execution/2026-10-16-feature/progress.md')

    def test_index_preserves_foreign_page(self):
        self.project.new('Feature')
        self.project.index()
        path = '/Knowledge/tests/index.md'
        self.assertIn('Feature', self.fake.nodes[path]['content'])
        self.fake.nodes[path]['metadata_json'] = '{}'
        with self.assertRaisesRegex(p.ProjectError, 'foreign'):
            self.project.index()

    def test_concurrent_foreign_creation_is_not_overwritten(self):
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/specs/2026-10-16-race-design.md')
        remote = '/Knowledge/tests/specs/2026-10-16-race-design.md'
        original = self.project._run
        def race(args):
            if 'write-node' in args and remote in args:
                self.fake.nodes[remote] = {'path': remote, 'kind': 'file', 'content': 'foreign data', 'metadata_json': '{}', 'etag': 'foreign'}
            return original(args)
        self.project._run = race
        with self.assertRaisesRegex(p.ProjectError, 'foreign'):
            self.project.document('spec', local, workflow_id=record['id'])
        self.assertEqual(self.fake.nodes[remote]['content'], 'foreign data')
        self.assertEqual(self.project.resolve(workflow_id=record['id'])['artifacts'], {})

    def test_publication_retry_after_manifest_update_failure(self):
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/specs/2026-10-16-retry-design.md')
        self.fake.fail = '/manifest.json'
        with self.assertRaises(p.ProjectError):
            self.project.document('spec', local, workflow_id=record['id'])
        remote = '/Knowledge/tests/specs/2026-10-16-retry-design.md'
        initial = dict(self.fake.nodes[remote])
        self.fake.fail = None
        result = self.project.document('spec', local, workflow_id=record['id'])
        self.assertEqual(self.fake.nodes[remote], initial)
        self.assertEqual(result['artifacts']['spec']['path'], remote)

    def test_registered_document_disappearance_is_error(self):
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/specs/2026-10-16-gone-design.md')
        result = self.project.document('spec', local, workflow_id=record['id'])
        del self.fake.nodes[result['artifacts']['spec']['path']]
        with self.assertRaisesRegex(p.ProjectError, 'missing'):
            self.project.document('spec', local, workflow_id=record['id'])

    def test_publication_baseline_allows_push_and_recovered_checkout(self):
        from test_cli_project import bridge
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/plans/2026-10-16-push.md')
        record = self.project.document('plan', local, workflow_id=record['id'])
        work = bridge.Workspace(self.project.config_path, self.project.transport, data=self.project.workspace_data(record), root=self.root)
        self.assertEqual(work.check('plan')['state'], 'clean')
        (self.root / local).write_text('# Plan\n\nChanged plan.\n')
        self.assertEqual(work.check('plan')['state'], 'local_changed')
        self.assertFalse(work.push('plan')['dirty'])
        checkout = self.root / 'other-checkout'
        checkout.mkdir()
        other = p.Project(checkout, config_path=self.project.config_path, run=self.fake)
        other.use(record['id'], 'other-chat')
        copied = bridge.Workspace(other.config_path, other.transport, data=other.workspace_data(record), root=checkout)
        copied.pull('plan')
        self.assertEqual((checkout / local).read_text(), (self.root / local).read_text())
        self.assertNotEqual(copied.artifact('plan')[2], work.artifact('plan')[2])

    def test_current_state_is_explicit_and_visible_in_index(self):
        record = self.project.new('Feature')
        result = self.project.state('Implementing task 2; waiting for test results.', workflow_id=record['id'])
        self.assertEqual(result['current_state'], 'Implementing task 2; waiting for test results.')
        self.assertIn(result['current_state'], self.project.index()['content'])
        self.assertEqual(result['artifacts'], {})
        self.assertNotIn(record['id'], self.project.index()['content'])

    def test_nested_spec_path_is_rejected(self):
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/specs/2026-10-16-nested/other-design.md')
        with self.assertRaisesRegex(p.ProjectError, 'upstream'):
            self.project.document('spec', local, workflow_id=record['id'])

    def test_manifest_swap_between_reads_is_rejected(self):
        first, other = self.project.new('First'), self.project.new('Other')
        local = self.authored('docs/superpowers/specs/2026-10-16-swap-design.md')
        original = self.project._read_node
        target = self.project._manifest_path(first['id'])
        seen = []
        def swapped(path):
            node = original(path)
            if path == target:
                seen.append(True)
                if len(seen) == 2:
                    node['content'] = json.dumps(other)
                    node['metadata_json'] = json.dumps(self.project._owner(other, 'manifest'))
            return node
        self.project._read_node = swapped
        with self.assertRaises(p.ProjectError):
            self.project.document('spec', local, workflow_id=first['id'])

    def test_foreign_workspace_marker_blocks_progress_publication(self):
        record = self.project.new('Feature')
        plan = self.authored('docs/superpowers/plans/2026-10-16-marker.md')
        progress = self.authored('.superpowers/sdd/2026-10-16-marker/progress.md', '# SDD ledger — plan: '+plan+'\n\nTask 1: pending\n')
        (self.root / progress).with_name('plan-path').write_text('docs/another-plan.md\n')
        self.project.document('plan', plan, workflow_id=record['id'])
        with self.assertRaisesRegex(p.ProjectError, 'workspace'):
            self.project.document('progress', progress, workflow_id=record['id'])

    def test_pull_progress_refuses_other_plan_workspace(self):
        from test_cli_project import bridge
        record = self.project.new('Feature')
        plan = self.authored('docs/superpowers/plans/2026-10-16-marker.md')
        progress = self.authored('.superpowers/sdd/2026-10-16-marker/progress.md', '# SDD ledger — plan: '+plan+'\n\nTask 1: pending\n')
        self.project.document('plan', plan, workflow_id=record['id'])
        record = self.project.document('progress', progress, workflow_id=record['id'])
        work = bridge.Workspace(self.project.config_path, self.project.transport, data=self.project.workspace_data(record), root=self.root)
        (self.root / progress).with_name('plan-path').write_text('docs/another-plan.md\n')
        with self.assertRaisesRegex(bridge.WorkflowError, 'workspace'):
            work.pull('progress')

    def test_restored_suffix_workspace_uses_current_checkout_helper_resolution(self):
        from test_cli_project import bridge
        record = self.project.new('Feature')
        plan = self.authored('docs/superpowers/plans/2026-10-16-collision.md')
        progress = self.authored('.superpowers/sdd/2026-10-16-collision-plans/progress.md', '# SDD ledger — plan: '+plan+'\n\nTask 1: pending\n')
        blocker = self.root / '.superpowers/sdd/2026-10-16-collision/plan-path'
        blocker.parent.mkdir(parents=True)
        blocker.write_text('other.md\n')
        self.project.document('plan', plan, workflow_id=record['id'])
        record = self.project.document('progress', progress, workflow_id=record['id'])
        checkout = self.root / 'restored'
        checkout.mkdir()
        other = p.Project(checkout, config_path=self.project.config_path, run=self.fake)
        copied = bridge.Workspace(other.config_path, other.transport, data=other.workspace_data(record), root=checkout)
        copied.pull('plan')
        copied.pull('progress')
        expected = checkout / '.superpowers/sdd/2026-10-16-collision/progress.md'
        self.assertEqual(expected.read_text(), (self.root / progress).read_text())
        self.assertEqual(record['artifacts']['progress']['local'], progress)
        self.assertEqual(copied.check('progress')['state'], 'clean')
        subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
        helper = Path(__file__).resolve().parents[2] / 'skills/subagent-driven-development/scripts/sdd-workspace'
        resolved = subprocess.run(['bash', str(helper), plan], cwd=checkout, check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(Path(resolved), expected.parent.resolve())
        self.assertEqual((Path(resolved) / 'plan-path').read_text().strip(), plan)
        self.assertEqual(copied.check('progress')['state'], 'clean')
        retried = other.document('progress', str(expected.relative_to(checkout)), workflow_id=record['id'])
        self.assertEqual(retried['artifacts'], record['artifacts'])
        self.assertNotEqual(copied.artifact('progress')[2].parent, self.root / '.superpowers/kinic')


    def test_unrelated_execution_directory_rejected_before_writes(self):
        record = self.project.new('Feature')
        plan = self.authored('docs/superpowers/plans/2026-10-16-directory.md')
        progress = self.authored('.superpowers/sdd/unrelated/progress.md', '# SDD ledger — plan: '+plan+'\n\nTask 1: pending\n')
        self.project.document('plan', plan, workflow_id=record['id'])
        before = dict(self.fake.nodes)
        with self.assertRaisesRegex(p.ProjectError, 'sdd-workspace'):
            self.project.document('progress', progress, workflow_id=record['id'])
        self.assertEqual(self.fake.nodes, before)

    def test_absolute_ledger_plan_identity_rejected_before_writes(self):
        record = self.project.new('Feature')
        plan = self.authored('docs/superpowers/plans/2026-10-16-absolute.md')
        progress = self.authored('.superpowers/sdd/2026-10-16-absolute/progress.md', '# SDD ledger — plan: '+str(self.project.root / plan)+'\n\nTask 1: pending\n')
        self.project.document('plan', plan, workflow_id=record['id'])
        before = dict(self.fake.nodes)
        with self.assertRaisesRegex(p.ProjectError, 'relative'):
            self.project.document('progress', progress, workflow_id=record['id'])
        self.assertEqual(self.fake.nodes, before)

    def test_published_spec_is_excluded_by_exact_path_only(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/specs/2026-10-16-test[1]-design.md')
        other = self.authored('docs/superpowers/specs/2026-10-16-test1-design.md')
        self.project.document('spec', local, workflow_id=record['id'])
        ignored = subprocess.run(['git', 'check-ignore', '--', local], cwd=self.root, capture_output=True)
        self.assertEqual(ignored.returncode, 0)
        self.assertEqual(subprocess.run(['git', 'check-ignore', '--', other], cwd=self.root, capture_output=True).returncode, 1)
        self.assertFalse((self.root / 'docs/superpowers/.gitignore').exists())
        self.project.document('spec', local, workflow_id=record['id'])
        patterns = (self.root / '.git/info/exclude').read_text().splitlines()
        self.assertEqual(sum(line.startswith('/docs/superpowers/specs/') for line in patterns), 1)

    def test_failed_publication_does_not_exclude_authored_file(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/specs/2026-10-16-failure-design.md')
        self.fake.fail = '/manifest.json'
        with self.assertRaises(p.ProjectError):
            self.project.document('spec', local, workflow_id=record['id'])
        self.assertEqual(subprocess.run(['git', 'check-ignore', '--', local], cwd=self.root, capture_output=True).returncode, 1)

    def test_published_tracked_spec_remains_tracked(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/specs/2026-10-16-tracked-design.md')
        subprocess.run(['git', 'add', '--', local], cwd=self.root, check=True)
        self.project.document('spec', local, workflow_id=record['id'])
        self.assertEqual(subprocess.run(['git', 'ls-files', '--error-unmatch', '--', local], cwd=self.root, capture_output=True).returncode, 0)
        exclude = self.root / '.git/info/exclude'
        self.assertNotIn(local, exclude.read_text())

    def test_worktree_pull_excludes_only_the_pulled_document(self):
        from test_cli_project import bridge
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'Fixture'], cwd=self.root, check=True, capture_output=True)
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/plans/2026-10-16-pulled.md')
        record = self.project.document('plan', local, workflow_id=record['id'])
        # Simulate publication from an older client that did not add exclusion.
        exclude = self.root / '.git/info/exclude'
        exclude.write_text('# Existing user exclusions\n')
        checkout = self.root / '.worktrees/restored'
        subprocess.run(['git', 'worktree', 'add', '--detach', str(checkout), 'HEAD'], cwd=self.root, check=True, capture_output=True)
        other = p.Project(checkout, config_path=self.project.config_path, run=self.fake)
        work = bridge.Workspace(other.config_path, other.transport, data=other.workspace_data(record), root=checkout)
        work.pull('plan')
        self.assertEqual(subprocess.run(['git', 'check-ignore', '--', local], cwd=checkout, capture_output=True).returncode, 0)
        self.assertTrue(exclude.read_text().startswith('# Existing user exclusions\n'))


    def test_publication_without_git_does_not_create_git_metadata(self):
        record = self.project.new('Feature')
        local = self.authored('docs/superpowers/specs/2026-10-16-no-git-design.md')
        self.project.document('spec', local, workflow_id=record['id'])
        self.assertFalse((self.root / '.git').exists())
