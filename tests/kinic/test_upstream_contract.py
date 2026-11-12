"""Pin upstream behavior; allow only explicit storage-adaptation blocks."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASE = 'bb92a77741419a4ab5f06e711a283343f1ada0c3'
SKILLS = ('brainstorming', 'writing-plans', 'executing-plans',
          'subagent-driven-development', 'requesting-code-review',
          'finishing-a-development-branch', 'verification-before-completion',
          'test-driven-development')

class UpstreamContractTests(unittest.TestCase):
    def test_behavior_bodies_match_pinned_upstream(self):
        for name in SKILLS:
            path = f'skills/{name}/SKILL.md'
            original = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT, text=True)
            current = (ROOT / path).read_text().replace('kinic-superpowers:', 'superpowers:')
            current = re.sub(r'<!-- KINIC STORAGE START -->.*?<!-- KINIC STORAGE END -->\n*', '', current, flags=re.S)
            # Frontmatter is discovery scope; compare the complete behavioral body.
            original = original.split('---', 2)[2].strip()
            current = current.split('---', 2)[2].strip()
            self.assertEqual(current, original, name)

    def test_referenced_helpers_and_prompts_match_upstream(self):
        roots = [f'skills/{name}' for name in SKILLS]
        paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE, *roots], cwd=ROOT, text=True).splitlines()
        for path in paths:
            if path.endswith('/SKILL.md'):
                continue
            original = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT, text=True)
            current = (ROOT / path).read_text().replace('kinic-superpowers:', 'superpowers:')
            # Explicit, documented code adaptations (see docs/kinic/upstream/contract.md).
            current = re.sub(r'// KINIC ADAPTATION START\n.*?// KINIC ADAPTATION END\n', '', current, flags=re.S)
            self.assertEqual(current, original, path)

    def test_protocol_does_not_impose_five_document_gate(self):
        protocol = (ROOT / 'skills/using-superpowers/references/kinic-workflow.md').read_text()
        self.assertNotIn('Pull/read all five roles', protocol)
        self.assertNotIn('Require renewed human approval', protocol)
        self.assertNotIn('If HEAD changed since review', protocol)
        self.assertIn('# SDD ledger — plan:', protocol)
