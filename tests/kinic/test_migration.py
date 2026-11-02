import sys
import unittest
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import kinic_migrate as m
from kinic_project import ProjectError


class Fake:
    config = {'database_id': 'db', 'canister_id': 'c', 'replica_host': 'h'}
    def __init__(self):
        self.nodes = {}
        self.deleted = []
        self.fail = False
    def add(self, path, kind='file', content='test'):
        self.nodes[path] = dict(path=path, kind=kind, content=content, metadata_json='{}', etag='1')
    def _read_node(self, path):
        return self.nodes.get(path)
    def transport(self, args):
        path = args[args.index('--path') + 1]
        if args[0] == 'list-children':
            return [dict(n) for p,n in self.nodes.items() if str(Path(p).parent) == path]
        if self.fail:
            self.fail = False
            self.nodes.pop(path)
            raise ProjectError('lost response')
        assert self.nodes[path]['etag'] == args[args.index('--expected-etag')+1]
        assert not any(p.startswith(path+'/') for p in self.nodes)
        self.nodes.pop(path)
        self.deleted.append(path)
        return {'path': path}


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal = Path(self.tmp.name)/'journal.json'
        self.p = Fake()
        self.prefix = m.ALLOWED_PREFIXES[1]
        self.p.add('/Knowledge', 'folder')
        self.p.add('/Knowledge/kinic-superpowers', 'folder')
        self.p.add(self.prefix, 'folder')
        self.p.add(self.prefix+'/a.md')
        self.p.add('/Knowledge/kept.md', content='real result')
    def snapshot(self):
        return m.snapshot(self.p, self.journal, [self.prefix], retained_paths=['/Knowledge/kept.md'])
    def test_dry_run_and_apply(self):
        self.snapshot()
        self.assertFalse(m.run(self.p,self.journal)['applied'])
        self.assertEqual(self.p.deleted, [])
        m.run(self.p,self.journal,apply=True)
        self.assertNotIn(self.prefix,self.p.nodes)
        self.assertIn('/Knowledge/kept.md',self.p.nodes)
    def test_changed_source_or_destination_blocks_all(self):
        for path in [self.prefix+'/a.md','/Knowledge/kept.md']:
            with self.subTest(path=path):
                if self.journal.exists(): self.journal.unlink()
                self.snapshot()
                self.p.nodes[path] = dict(self.p.nodes[path], etag='2')
                with self.assertRaises(ProjectError): m.run(self.p,self.journal,apply=True)
                self.assertEqual(self.p.deleted,[])
    def test_surviving_reference_blocks(self):
        self.snapshot()
        self.p.add('/Knowledge/ref.md',content='See '+self.prefix+'/a.md')
        with self.assertRaises(ProjectError): m.run(self.p,self.journal,apply=True)
    def test_relative_and_encoded_surviving_links_block(self):
        links = [
            '[old](onboarding-20261015/a.md)',
            '[folder](onboarding-20261015)',
            '[parent](./docs/../onboarding-20261015/a.md)',
            '[[onboarding-20261015/a.md|Old]]',
            '[old](./onboarding-20261015/a.md#section)',
            '[old](onboarding%2D20261015/a.md)',
            '[old](%2FKnowledge%2Fkinic-superpowers%2Fonboarding-20261015%2Fa.md)',
            '[old][target]\n\n[target]: onboarding-20261015/a.md "title"',
            '<a href="onboarding-20261015/a.md">Old</a>',
        ]
        self.snapshot()
        for link in links:
            with self.subTest(link=link):
                self.p.add('/Knowledge/kinic-superpowers/index.md', content=link)
                with self.assertRaisesRegex(ProjectError, 'surviving reference'):
                    m.run(self.p, self.journal, apply=True)
                self.assertEqual(self.p.deleted, [])

    def test_parent_relative_metadata_reference_blocks(self):
        self.snapshot()
        self.p.add('/Knowledge/kinic-superpowers/docs', kind='folder')
        path = '/Knowledge/kinic-superpowers/docs/index.md'
        self.p.add(path, content='Navigation')
        self.p.nodes[path]['metadata_json'] = '{"source": "../onboarding-20261015/a.md"}'
        with self.assertRaisesRegex(ProjectError, 'surviving reference'):
            m.run(self.p, self.journal, apply=True)
        self.assertEqual(self.p.deleted, [])

    def test_unrelated_relative_link_does_not_block(self):
        self.snapshot()
        self.p.add('/Knowledge/kinic-superpowers/index.md', content='[keep](../kept.md)')
        self.assertTrue(m.run(self.p, self.journal, apply=True)['applied'])

    def test_new_child_blocks(self):
        self.snapshot()
        self.p.add(self.prefix+'/new.md')
        with self.assertRaises(ProjectError): m.run(self.p,self.journal,apply=True)
        self.assertEqual(self.p.deleted,[])
    def test_ambiguous_delete_resumes(self):
        self.snapshot()
        self.p.fail=True
        with self.assertRaises(ProjectError): m.run(self.p,self.journal,apply=True)
        m.run(self.p,self.journal,apply=True)
        self.assertNotIn(self.prefix,self.p.nodes)
    def test_connection_mismatch_blocks(self):
        self.snapshot()
        self.p.config = dict(self.p.config, database_id='different')
        with self.assertRaises(ProjectError): m.run(self.p,self.journal,apply=True)
        self.assertEqual(self.p.deleted,[])
    def test_inventory_bound_and_missing_source(self):
        with self.assertRaises(ProjectError): m.inventory(self.p, limit=2)
        self.snapshot()
        self.p.nodes.pop(self.prefix+'/a.md')
        with self.assertRaises(ProjectError): m.run(self.p,self.journal,apply=True)
    def test_journal_preserves_complete_evidence(self):
        record = self.snapshot()
        old = record['nodes'][self.prefix+'/a.md']
        m.run(self.p,self.journal,apply=True)
        import json
        saved = json.loads(self.journal.read_text())
        self.assertEqual(saved['nodes'][self.prefix+'/a.md'], old)
        self.assertEqual(saved['retained']['/Knowledge/kept.md']['content'], 'real result')
        self.assertTrue(saved['log'])
    def test_boundaries_and_existing_journal(self):
        with self.assertRaises(ProjectError): m.snapshot(self.p,self.journal,['/Knowledge'])
        self.snapshot()
        with self.assertRaises(ProjectError): self.snapshot()

if __name__ == '__main__': unittest.main()
