from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_repository.py"


class RepositoryValidationTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("validate_repository", SCRIPT)
        self.validator = importlib.util.module_from_spec(spec)
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
