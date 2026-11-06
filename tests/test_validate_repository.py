from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_repository.py"


class RepositoryValidationTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("validate_repository", SCRIPT)
        self.validator = importlib.util.module_from_spec(spec)
        with patch.object(sys, "path", [str(SCRIPT.parent), *sys.path]):
            spec.loader.exec_module(self.validator)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "VERSION").write_text("1.2.3\n")
        self.skill = self.root / "skills/example"
        self.skill.mkdir(parents=True)
        self.write_skill()

    def write_skill(self, version="1.2.3", body=""):
        (self.skill / "SKILL.md").write_text(
            f"---\nname: example\ndescription: An example.\nmetadata:\n  version: {version}\n---\n\n{body}\n"
        )

    def test_version_failure_is_not_masked_by_later_success(self):
        self.write_skill(version="1.2.2")
        with patch.object(self.validator, "run_check", return_value=0) as external:
            self.assertEqual(self.validator.main(["--root", str(self.root)]), 1)
        external.assert_not_called()

    def test_valid_resources_stay_valid_in_a_standalone_skill(self):
        resource = self.skill / "references/example.md"
        resource.parent.mkdir()
        resource.write_text("# Example\n")
        self.write_skill(body="[Example](references/example.md#example) and [Web](https://example.com).")
        self.assertEqual(self.validator.check_packages(self.root), [])

    def test_missing_and_cross_package_resources_fail(self):
        sibling = self.root / "skills/other/references/example.md"
        sibling.parent.mkdir(parents=True)
        sibling.write_text("# Exists only in another package\n")
        (sibling.parents[1] / "SKILL.md").write_text(
            "---\nname: other\ndescription: Another.\nmetadata:\n  version: 1.2.3\n---\n"
        )
        self.write_skill(body="[Other](../other/references/example.md)\n[Missing](assets/missing.json)")
        errors = self.validator.check_packages(self.root)
        self.assertTrue(any("outside" in error for error in errors), errors)
        self.assertTrue(any("missing" in error for error in errors), errors)

    def test_resource_references_are_checked_recursively(self):
        resource = self.skill / "references/example.md"
        resource.parent.mkdir()
        resource.write_text("[Missing](missing.md)\n")
        self.write_skill(body="[Example](references/example.md)")
        self.assertTrue(self.validator.check_packages(self.root))

    def test_repository_validation_rejects_drift_in_generated_query_tools(self):
        owner = self.root / 'skills/aitasks-maintenance'
        consumer = self.root / 'skills/code-review'
        for path in (owner, consumer):
            path.mkdir()
            (path / 'SKILL.md').write_text(
                f'---\nname: {path.name}\ndescription: Query example.\nmetadata:\n  version: 1.2.3\n---\n')
        for relative, body in (('scripts/query_aitasks.py', 'print("query")\n'),
                               ('assets/search-aliases.json', '[]\n')):
            for path in (owner / relative, consumer / relative):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body)
        self.assertEqual(self.validator.check_packages(self.root), [])
        (consumer / 'scripts/query_aitasks.py').write_text('print("different parser")\n')
        errors = self.validator.check_packages(self.root)
        self.assertTrue(any('generated content or permissions differ' in error for error in errors), errors)

    def test_existing_but_excluded_resource_cannot_pass_standalone_validation(self):
        resource = self.skill / "scripts/tool.pyc"
        resource.parent.mkdir()
        resource.write_bytes(b"compiled resource")
        self.write_skill(body="[Runtime](scripts/tool.pyc)")
        errors = self.validator.check_packages(self.root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("resource is excluded from distribution: scripts/tool.pyc", errors[0])

    def test_excluded_markdown_is_not_part_of_the_package_validation(self):
        cached = self.skill / "__pycache__/stale.md"
        cached.parent.mkdir()
        cached.write_text("[Old link](missing.md)\n")
        self.assertEqual(self.validator.check_packages(self.root), [])

    def test_directory_links_require_actual_distributed_descendants(self):
        (self.skill / "references/empty").mkdir(parents=True)
        (self.skill / "__pycache__/nested").mkdir(parents=True)
        (self.skill / "references/guide.md").write_text("# Guide\n")
        self.write_skill(body="[Examples](references/)")
        self.assertEqual(self.validator.check_packages(self.root), [])
        self.write_skill(body="[Examples](references/empty/)")
        errors = self.validator.check_packages(self.root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("directory has no distributed files: references/empty/", errors[0])
        filtered = self.skill / "references/filtered/tool.pyc"
        filtered.parent.mkdir()
        filtered.write_bytes(b"compiled resource")
        self.write_skill(body="[Runtime](references/filtered/)")
        errors = self.validator.check_packages(self.root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("directory has no distributed files: references/filtered/", errors[0])
        self.write_skill(body="[Cache](__pycache__/nested/)")
        errors = self.validator.check_packages(self.root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("directory has no distributed files: __pycache__/nested/", errors[0])

    def test_inline_links_support_titles_and_angle_bracket_destinations(self):
        resources = self.skill / "references"
        resources.mkdir()
        (resources / "example.md").write_text("# Example\n")
        (resources / "example(1).md").write_text("# Numbered example\n")
        (resources / "guide with spaces.md").write_text("# Guide\n")
        self.write_skill(body='[Example](references/example.md "Usage guide")\n'
                              '[Guide](<references/guide with spaces.md> "A second guide")\n'
                              '[Numbered](references/example(1).md)')
        self.assertEqual(self.validator.check_packages(self.root), [])

    def test_fenced_and_inline_code_examples_are_not_resource_links(self):
        self.write_skill(body='```markdown\n[Example](missing-in-fence.md)\n```\n'
                              '~~~markdown\n[Reference][sample]\n[sample]: ../other/SKILL.md\n~~~\n'
                              '`[Example](missing-inline.md)`\n')
        self.assertEqual(self.validator.check_packages(self.root), [])
        self.write_skill(body='`[Example](missing-inline.md)`\n[Actual](missing-real.md)\n')
        errors = self.validator.check_packages(self.root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("missing-real.md", errors[0])

    def test_used_reference_links_cannot_escape_standalone_package(self):
        sibling = self.root / "skills/other"
        sibling.mkdir()
        (sibling / "SKILL.md").write_text("---\nname: other\nmetadata:\n  version: 1.2.3\n---\n")
        self.write_skill(body='[Other][GUIDE]\n\n[guide]: ../other/SKILL.md "Other Skill"\n')
        errors = self.validator.check_packages(self.root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("outside standalone package", errors[0])

    def test_staged_whitespace_is_not_masked_by_clean_worktree(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        self.write_skill(body="Staged trailing whitespace. ")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True, capture_output=True)
        self.assertNotEqual(self.validator.main(["--root", str(self.root), "--offline"]), 0)

    def test_collapsed_and_shortcut_references_resolve_only_used_definitions(self):
        resource = self.skill / "guide.md"
        resource.write_text("# Guide\n")
        self.write_skill(body='[GUIDE][] and [guide].\n\n[guide]: guide.md\n[unused]: missing.md\n')
        self.assertEqual(self.validator.check_packages(self.root), [])
        resource.unlink()
        errors = self.validator.check_packages(self.root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("missing resource: guide.md", errors[0])

    def test_validator_failure_stops_before_tests(self):
        with patch.object(self.validator, "run_check", return_value=7) as external:
            self.assertEqual(self.validator.main(["--root", str(self.root), "--tests"]), 7)
        self.assertEqual(external.call_count, 1)

    def test_empty_skill_inventory_and_missing_version_fail(self):
        (self.skill / "SKILL.md").unlink()
        (self.root / "VERSION").unlink()
        self.assertGreaterEqual(len(self.validator.check_packages(self.root)), 2)


if __name__ == "__main__":
    unittest.main()
