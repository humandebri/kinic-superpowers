"""Shared CLI resolution, migration, and read-only diagnostics contracts."""
import json
from pathlib import Path
import tempfile
import unittest
from test_project import p, Fake


class SharedCLI(Fake):
    def __init__(self):
        super().__init__()
        self.connection = {'database_id': 'db', 'canister_id': 'canister', 'replica_host': 'https://icp-api.io'}
        self.doctor_result = {'checks': [{'id': 'identity', 'status': 'ok'}, {'id': 'database.caller', 'status': 'ok'}, {'id': 'database.read', 'status': 'ok'}, {'id': 'api.read_node', 'status': 'ok'}, {'id': 'api.scope_revision', 'status': 'unknown'}, {'id': 'plugin.codex', 'status': 'warning'}]}

    def __call__(self, args):
        if 'current' in args:
            self.calls.append(args)
            return dict(self.connection)
        if 'link' in args:
            self.calls.append(args)
            self.connection['database_id'] = args[-1]
            return {'path': '.kinic/config.toml'}
        if 'doctor' in args:
            self.calls.append(args)
            return self.doctor_result
        return super().__call__(args)


class SharedSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cli = SharedCLI()
        self.path = self.root / '.kinic-superpowers.json'

    def init(self, **kw):
        return p.initialize(self.root, 'db', '/Knowledge/tests', run=self.cli, **kw)

    def snapshot(self):
        return {str(f): f.read_bytes() for f in self.root.rglob('*') if f.is_file()}

    def test_fresh_init_links_then_reads_unpinned_effective_connection(self):
        config = self.init()
        self.assertEqual(config['version'], 3)
        link = next(i for i, call in enumerate(self.cli.calls) if 'link' in call)
        self.assertTrue(any('current' in c and '--database-id' not in c for c in self.cli.calls[link + 1:]))

    def test_effective_destination_drift_is_rejected_before_document_read(self):
        self.init()
        for key in ('database_id', 'canister_id', 'replica_host'):
            with self.subTest(key=key):
                saved = self.cli.connection[key]
                self.cli.connection[key] = 'changed'
                self.cli.calls.clear()
                with self.assertRaisesRegex(p.ProjectError, 'binding|connection'):
                    p.Project(self.root, run=self.cli).transport(['read-node', '--path', '/Knowledge/tests', '--json'])
                self.assertFalse(any('read-node' in c for c in self.cli.calls))
                self.cli.connection[key] = saved

    def test_checked_connection_is_pinned_after_identity_check(self):
        self.init()
        def race(args):
            result = self.cli(args)
            if 'show' in args:
                self.cli.connection['database_id'] = 'raced'
            return result
        p.Project(self.root, run=race).transport(['status', '--json'])
        call = self.cli.calls[-1]
        self.assertEqual(call[call.index('--database-id') + 1], 'db')

    def test_v2_migration_preserves_binding_fields_backup_and_fingerprint(self):
        old = self.init()
        old.update(version=2, project_id='project-1', project_name='sample')
        self.path.write_text(json.dumps(old))
        before = self.snapshot()
        p.initialize(self.root, inspect=True, run=self.cli)
        self.assertEqual(self.snapshot(), before)
        result = p.initialize(self.root, migrate=True, run=self.cli)
        self.assertEqual(result['version'], 3)
        self.assertEqual(result['project_id'], 'project-1')
        self.assertEqual(p.fingerprint(result), p.fingerprint(old))
        backup = self.path.with_name(self.path.name + '.v2-backup')
        self.assertEqual(json.loads(backup.read_text()), old)
        self.assertEqual(p.initialize(self.root, migrate=True, run=self.cli), result)

    def test_migration_conflict_preserves_all_local_files(self):
        old = self.init()
        old['version'] = 2
        self.path.write_text(json.dumps(old))
        self.cli.connection['database_id'] = 'other'
        before = self.snapshot()
        with self.assertRaisesRegex(p.ProjectError, 'conflict|binding|connection'):
            p.initialize(self.root, migrate=True, run=self.cli)
        self.assertEqual(self.snapshot(), before)

    def test_doctor_optional_unknown_does_not_block_document_transport_and_writes_nothing(self):
        self.init()
        before = self.snapshot()
        self.cli.calls.clear()
        result = p.Project(self.root, run=self.cli).doctor(session='unselected')
        self.assertFalse(any('show' in c or 'status' in c or 'link' in c for c in self.cli.calls))
        self.assertEqual(result['document_transport'], 'ok')
        optional = [c for c in result['checks'] if c['id'] == 'api.scope_revision'][0]
        self.assertEqual(optional['status'], 'unknown')
        self.assertFalse(optional['required'])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(any('doctor' in c for c in self.cli.calls))

    def test_doctor_failed_transport_is_unknown_not_success(self):
        self.init()
        self.cli.doctor_result['checks'][2]['status'] = 'unknown'
        result = p.Project(self.root, run=self.cli).doctor()
        self.assertEqual(result['document_transport'], 'unknown')

    def test_doctor_unknown_identity_blocks_document_transport(self):
        self.init()
        self.cli.doctor_result['checks'][0]['status'] = 'unknown'
        result = p.Project(self.root, run=self.cli).doctor()
        self.assertNotEqual(result['document_transport'], 'ok')

    def test_v2_backup_survives_failed_readback_and_retry(self):
        old = self.init()
        old['version'] = 2
        self.path.write_text(json.dumps(old))
        calls = []
        def interrupted(args):
            value = self.cli(args)
            if 'link' in args:
                calls.append(True)
            if 'current' in args and calls:
                raise p.ProjectError('readback interrupted')
            return value
        with self.assertRaisesRegex(p.ProjectError, 'interrupted'):
            p.initialize(self.root, migrate=True, run=interrupted)
        self.assertEqual(json.loads(self.path.read_text()), old)
        self.assertEqual(json.loads(self.path.with_name(self.path.name + '.v2-backup').read_text()), old)
        self.assertEqual(p.initialize(self.root, migrate=True, run=self.cli)['version'], 3)

    def test_v2_operations_still_use_saved_connection_without_common_settings(self):
        old = self.init()
        old['version'] = 2
        self.path.write_text(json.dumps(old))
        self.cli.connection['database_id'] = 'other'
        self.cli.calls.clear()
        p.Project(self.root, run=self.cli).transport(['status', '--json'])
        self.assertFalse(any('current' in c for c in self.cli.calls))
        self.assertEqual(self.cli.calls[-1][self.cli.calls[-1].index('--database-id') + 1], 'db')

    def test_doctor_distinguishes_binding_mismatch_from_unavailable_diagnostics(self):
        self.init()
        self.cli.connection['database_id'] = 'other'
        result = p.Project(self.root, run=self.cli).doctor()
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['document_transport'], 'error')

    def test_shared_config_resolution_runs_in_primary_checkout(self):
        from unittest.mock import patch
        self.init()
        admin = self.root / '.git/worktrees/child'
        admin.mkdir(parents=True)
        (admin / 'commondir').write_text('../..')
        child = self.root / 'child'
        child.mkdir()
        (child / '.git').write_text('gitdir: ' + str(admin))
        seen = []
        def invoke(cli, cwd, args):
            seen.append(cwd)
            return self.cli(args)
        with patch.object(p, '_invoke', side_effect=invoke):
            project = p.Project(child)
            project.transport(['status', '--json'])
        self.assertEqual(project.root, child.resolve())
        self.assertTrue(seen)
        self.assertEqual(set(seen), {self.root.resolve()})

    def test_doctor_script_does_not_create_import_cache(self):
        import shutil
        import subprocess
        import sys
        install = self.root / 'install'
        install.mkdir()
        source = Path(p.__file__).parent
        for file in source.glob('*.py'):
            shutil.copyfile(file, install / file.name)
        self.path.write_text('{"version": 999}')
        before = self.snapshot()
        result = subprocess.run([sys.executable, str(install / 'kinic-workflow.py'),
                                 '--project-root', str(self.root), 'doctor', '--json'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['status'], 'error')
        self.assertEqual(self.snapshot(), before)

    def test_legacy_doctor_uses_saved_transport_when_common_database_is_unset(self):
        saved = self.init()
        for version in (1, 2):
            with self.subTest(version=version):
                legacy = dict(saved, version=version)
                if version == 1:
                    legacy = {'version': 1, 'database_id': 'db', 'artifacts': {}}
                self.path.write_text(json.dumps(legacy))
                self.cli.connection['database_id'] = None
                self.cli.calls.clear()
                before = self.snapshot()
                result = p.Project(self.root, run=self.cli).doctor()
                self.assertEqual(result['document_transport'], 'ok')
                self.assertEqual(result['status'], 'unknown')
                call = next(c for c in self.cli.calls if 'doctor' in c)
                self.assertEqual(call[call.index('--database-id') + 1], 'db')
                if version == 2:
                    self.assertEqual(call[call.index('--canister-id') + 1], 'canister')
                    self.assertEqual(call[call.index('--replica-host') + 1], 'https://icp-api.io')
                self.assertFalse(any('show' in c or 'status' in c or 'link' in c for c in self.cli.calls))
                self.assertEqual(self.snapshot(), before)
