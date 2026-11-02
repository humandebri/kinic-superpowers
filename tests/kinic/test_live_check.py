"""Offline checks for live-test result classification. Never calls the wiki."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'live_check', Path(__file__).resolve().parents[2] / 'scripts/kinic-live-check.py')
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class ConflictClassificationTests(unittest.TestCase):
    def test_unrelated_decode_error_is_not_a_conflict(self):
        self.assertFalse(live.is_etag_conflict(
            'code : variant { EtagConflict; NotFound; }; '
            'unknown variant `NotFound`, expected one of `etag_conflict`, `not_found`'))

    def test_server_conflict_with_cli_decode_bug_is_recognized(self):
        self.assertTrue(live.is_etag_conflict(
            'Deserialize error: unknown variant `EtagConflict`, expected one of `etag_conflict`'))

    def test_normal_server_conflict_is_recognized(self):
        self.assertTrue(live.is_etag_conflict('expected_etag does not match current etag: /test.md'))

class FixtureCleanupTests(unittest.TestCase):
    def test_cleanup_refuses_knowledge_scope(self):
        self.assertTrue(hasattr(live, 'cleanup_fixture'))
        with self.assertRaises(ValueError):
            live.cleanup_fixture(lambda args: self.fail('must not call CLI'), [], '/Knowledge/test', {})
    def test_cleanup_uses_captured_etags(self):
        self.assertTrue(hasattr(live, 'cleanup_fixture'))
        calls=[]
        def cli(args):
            calls.append(args)
            return [] if 'list-nodes' in args else {}
        prefix='/Testing/kinic-superpowers/run'
        live.cleanup_fixture(cli, [], prefix, {prefix+'/spec.md':'etag-before',prefix:'folder-etag'})
        deletes=[x for x in calls if 'delete-node' in x]
        self.assertEqual([x[x.index('--expected-etag')+1] for x in deletes], ['etag-before','folder-etag'])
