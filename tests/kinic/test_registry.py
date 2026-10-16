"""Stable repository registration and foreign namespace protection."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import kinic_project as p
import kinic_registry as r


class Stub:
    def __init__(self, root, nodes=None):
        self.root = root
        self.config_path = root / '.kinic-superpowers.json'
        self.config = {'version': 2, 'scope': '/Knowledge/projects/demo'}
        self.config_path.write_text(json.dumps(self.config))
        self.nodes = nodes if nodes is not None else {}
    def _read_node(self, path):
        return self.nodes.get(path)
    def _owner(self, rec, role):
        return {'kinic_superpowers': {'workflow_id': rec['id'], 'nonce': rec['nonce'], 'role': role}}
    def _verify_owner(self, node, rec, role):
        if json.loads(node['metadata_json']) != self._owner(rec, role):
            raise p.ProjectError('foreign owner')
    def _write(self, path, content, rec, role, etag=None):
        if path in self.nodes:
            raise p.ProjectError('etag conflict')
        node = dict(path=path, content=content, metadata_json=json.dumps(self._owner(rec, role)), etag='1', kind='file')
        self.nodes[path] = node
        return node
    def transport(self, args):
        path = args[args.index('--path') + 1]
        if args[0] == 'list-children':
            return [v for k, v in self.nodes.items() if str(Path(k).parent) == path]
        self.nodes[path] = dict(path=path, kind='folder', etag='1')


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = Stub(self.root)
    def test_remote_schemes_and_credentials_normalized(self):
        for remote in ['git@github.com:Owner/Demo.git', 'https://secret:token@github.com/Owner/Demo.git', 'ssh://git@github.com/Owner/Demo.git']:
            with patch.object(r, '_git', return_value=remote):
                self.assertEqual(r.propose(self.root), {'project_name': 'demo', 'repository_key': 'github.com/owner/demo'})
    def test_local_remote_does_not_leak_path(self):
        with patch.object(r, '_git', return_value='/Users/private/repo'):
            self.assertIsNone(r.propose(self.root)['repository_key'])
    def test_clones_reuse_registered_uuid(self):
        with patch.object(r, 'propose', return_value={'project_name': 'demo', 'repository_key': 'github.com/org/demo'}):
            first = r.register(self.project)
            other = self.root / 'clone'; other.mkdir()
            second = r.register(Stub(other, self.project.nodes))
        self.assertEqual(first['project_id'], second['project_id'])
    def test_foreign_repository_collision_no_config_change(self):
        with patch.object(r, 'propose', return_value={'project_name': 'demo', 'repository_key': 'github.com/org/demo'}):
            r.register(self.project)
        other = self.root / 'other'; other.mkdir()
        candidate = Stub(other, self.project.nodes)
        before = candidate.config_path.read_text()
        with patch.object(r, 'propose', return_value={'project_name': 'demo', 'repository_key': 'github.com/other/demo'}):
            with self.assertRaisesRegex(p.ProjectError, 'collision'):
                r.register(candidate)
        self.assertEqual(before, candidate.config_path.read_text())
    def test_local_identity_persisted_and_idempotent(self):
        with patch.object(r, 'propose', return_value={'project_name': 'demo', 'repository_key': None}):
            first = r.register(self.project)
            second = r.register(self.project)
        self.assertEqual(first, second)
        self.assertTrue(first['repository_key'].startswith('local:'))
        self.assertNotIn(str(self.root), json.dumps(self.project.nodes))
    def test_existing_workflows_refuse_scope_change(self):
        self.project.nodes[self.project.config['scope'] + '/workflows'] = {'kind': 'folder', 'path': self.project.config['scope'] + '/workflows'}
        with self.assertRaisesRegex(p.ProjectError, 'migration'):
            r.register(self.project, 'different')
    def test_foreign_metadata_rejected(self):
        with patch.object(r, 'propose', return_value={'project_name': 'demo', 'repository_key': 'github.com/org/demo'}):
            r.register(self.project)
            self.project.nodes[self.project.config['scope'] + '/project.json']['metadata_json'] = '{}'
            with self.assertRaises(p.ProjectError):
                r.register(self.project)
    def test_real_git_linked_worktree_has_same_proposal(self):
        def git(*args):
            subprocess.run(['git', '-C', str(self.root), *args], check=True,
                           capture_output=True, text=True)
        git('init')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.com',
            'commit', '--allow-empty', '-m', 'Initial fixture')
        git('remote', 'add', 'origin', 'git@github.com:Owner/Demo.git')
        worktree = self.root / '.worktrees' / 'test'
        git('worktree', 'add', '--detach', str(worktree))
        self.assertEqual(r.propose(self.root), r.propose(worktree))

    def test_registration_acknowledgement_loss_recovers(self):
        original = self.project._write
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise p.ProjectError('network timeout')
        self.project._write = lost
        with patch.object(r, 'propose', return_value={'project_name': 'demo', 'repository_key': 'github.com/org/demo'}):
            result = r.register(self.project)
        self.assertEqual(result['project_id'], json.loads(self.project.nodes[result['scope'] + '/project.json']['content'])['id'])

    def test_existing_fixed_id_replacement_refused(self):
        with patch.object(r, 'propose', return_value={'project_name': 'demo', 'repository_key': 'github.com/org/demo'}):
            r.register(self.project)
            self.project.config['project_id'] = '00000000-0000-0000-0000-000000000000'
            with self.assertRaisesRegex(p.ProjectError, 'id changed'):
                r.register(self.project)

    def test_testing_scope_preserved(self):
        self.project.config['scope'] = '/Testing/kinic-superpowers/demo'
        with patch.object(r, 'propose', return_value={'project_name': 'demo', 'repository_key': None}):
            result = r.register(self.project)
        self.assertEqual(result['scope'], '/Testing/kinic-superpowers/demo')

if __name__ == '__main__': unittest.main()

class RegistryWiringTests(unittest.TestCase):
    def test_default_scope_uses_repository_name_without_location_hash(self):
        with patch.object(r, 'propose', return_value={'project_name': 'demo', 'repository_key': 'github.com/org/demo'}):
            self.assertEqual(p._default_scope(Path('/arbitrary/checkout')), '/Knowledge/projects/demo')
    def test_project_register_command_is_available(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('registry_cli', Path(__file__).resolve().parents[2] / 'scripts/kinic-workflow.py')
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        args = cli.argument_parser().parse_args(['project', 'register', '--name', 'demo'])
        self.assertEqual((args.command, args.action, args.name), ('project', 'register', 'demo'))
    def test_isolated_test_namespace_is_supported(self):
        self.assertEqual(p._path('/Testing/kinic-superpowers/run'), '/Testing/kinic-superpowers/run')
        with self.assertRaises(p.ProjectError):
            p._path('/Testing/unrelated/run')
