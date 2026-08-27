from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "bootstrap_project.py"
SOURCE_SKILLS = sorted(path.name for path in (REPOSITORY_ROOT / "skills").iterdir())


class BootstrapProjectTest(unittest.TestCase):
    def run_script(
        self, *arguments: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_installs_idempotently_without_overwriting_existing_agents_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            target.mkdir()
            (target / "AGENTS.md").write_text("# Existing project rules\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(target)], check=True)

            first = self.run_script("--target", str(target))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(
                sorted(path.name for path in (target / ".agents" / "skills").iterdir()),
                SOURCE_SKILLS,
            )
            agents_after_first = (target / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("# Existing project rules", agents_after_first)
            self.assertEqual(agents_after_first.count("ai-engineering-collaboration:begin"), 1)
            self.assertIn(".aitasks/", (target / ".gitignore").read_text(encoding="utf-8"))

            second = self.run_script("--target", str(target))
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn(
                f"Skills: 0 installed, {len(SOURCE_SKILLS)} already current.", second.stdout
            )
            self.assertEqual(
                agents_after_first, (target / "AGENTS.md").read_text(encoding="utf-8")
            )

    def test_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            target.mkdir()

            result = self.run_script("--target", str(target), "--dry-run")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("install ai-engineering-collaboration", result.stdout)
            self.assertFalse((target / ".agents").exists())
            self.assertFalse((target / "AGENTS.md").exists())
            self.assertFalse((target / ".gitignore").exists())

    def test_track_aitasks_leaves_gitignore_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            target.mkdir()

            result = self.run_script("--target", str(target), "--track-aitasks")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((target / ".gitignore").exists())

    def test_prints_custom_instructions_without_a_target(self) -> None:
        result = self.run_script("--print-custom-instructions")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Engineering defaults", result.stdout)
        self.assertIn("使用中文回复", result.stdout)

    def test_user_scope_installs_only_skills_under_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            environment = dict(os.environ, HOME=str(home))

            first = self.run_script("--scope", "user", environment=environment)
            self.assertEqual(first.returncode, 0, first.stderr)
            skills = home / ".agents" / "skills"
            self.assertEqual(sorted(path.name for path in skills.iterdir()), SOURCE_SKILLS)
            self.assertFalse((home / "AGENTS.md").exists())
            self.assertFalse((home / ".gitignore").exists())

            second = self.run_script("--scope", "user", environment=environment)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn(
                f"User Skills: 0 installed, {len(SOURCE_SKILLS)} already current.",
                second.stdout,
            )

    def test_conflicting_skill_aborts_before_writing_other_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            conflicting_skill = target / ".agents" / "skills" / "ai-engineering-collaboration"
            conflicting_skill.mkdir(parents=True)
            (conflicting_skill / "SKILL.md").write_text("modified\n", encoding="utf-8")

            result = self.run_script("--target", str(target))

            self.assertEqual(result.returncode, 2)
            self.assertIn("differs from the source Skill", result.stderr)
            self.assertFalse((target / "AGENTS.md").exists())
            self.assertFalse((target / ".gitignore").exists())


if __name__ == "__main__":
    unittest.main()
