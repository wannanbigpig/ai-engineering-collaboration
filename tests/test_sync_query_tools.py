import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/sync_query_tools.py'
SPEC = importlib.util.spec_from_file_location('sync_query_tools', SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class SyncQueryToolsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('aitasks-maintenance', *sync.CONSUMERS):
            path = self.root / 'skills' / name / 'SKILL.md'
            path.parent.mkdir(parents=True)
            path.write_text(f'# {name}\n')
        for resource in sync.RESOURCES:
            path = self.root / 'skills/aitasks-maintenance' / resource
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('[]\n' if path.suffix == '.json' else 'print("read only")\n')
        (self.root / 'skills/aitasks-maintenance/scripts/query_aitasks.py').chmod(0o755)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
                for p in self.root.rglob('*') if p.is_file()}

    def test_generated_tools_match_source_and_checks_are_read_only(self):
        self.assertTrue(sync.check_query_tools(self.root))
        sync.sync_query_tools(self.root)
        self.assertEqual(sync.check_query_tools(self.root), [])
        for target, source in sync.query_tool_copies(self.root).items():
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), stat.S_IMODE(source.stat().st_mode))
        before = self.snapshot()
        self.assertEqual(sync.check_query_tools(self.root), [])
        sync.sync_query_tools(self.root)
        self.assertEqual(self.snapshot(), before)

    def test_source_and_generated_drift_are_detected_and_rebuilt(self):
        sync.sync_query_tools(self.root)
        source = self.root / 'skills/aitasks-maintenance/scripts/query_aitasks.py'
        source.write_text('print("updated")\n')
        self.assertEqual(len(sync.check_query_tools(self.root)), len(sync.CONSUMERS))
        before = self.snapshot()
        sync.check_query_tools(self.root)
        self.assertEqual(self.snapshot(), before)
        sync.sync_query_tools(self.root)
        target = self.root / 'skills/code-review/scripts/query_aitasks.py'
        target.chmod(0o600)
        self.assertEqual(len(sync.check_query_tools(self.root)), 1)
        sync.sync_query_tools(self.root)
        self.assertEqual(sync.check_query_tools(self.root), [])

    def test_redirected_generated_resource_is_rejected_before_other_writes(self):
        target = self.root / 'skills/code-review/scripts/query_aitasks.py'
        target.parent.mkdir()
        outside = self.root / 'keep.py'
        outside.write_text('user content\n')
        target.symlink_to(outside)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'symbolic links'):
            sync.sync_query_tools(self.root)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
