from __future__ import annotations

import os
import shutil
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

    def test_project_target_links_skills_for_gemini(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            target.mkdir()

            first = self.run_script("--target", str(target))
            self.assertEqual(first.returncode, 0, first.stderr)
            gemini_skills = target / ".gemini" / "skills"
            self.assertEqual(sorted(path.name for path in gemini_skills.iterdir()), SOURCE_SKILLS)
            for name in SOURCE_SKILLS:
                link = gemini_skills / name
                self.assertTrue(link.is_symlink(), link)
                self.assertEqual(
                    link.resolve(), (target / ".agents" / "skills" / name).resolve()
                )
            self.assertIn(
                f"Gemini: {len(SOURCE_SKILLS)} linked, 0 already current", first.stdout
            )

            second = self.run_script("--target", str(target))
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn(
                f"Gemini: 0 linked, {len(SOURCE_SKILLS)} already current", second.stdout
            )

    def test_project_dry_run_reports_gemini_links_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            target.mkdir()

            result = self.run_script("--target", str(target), "--dry-run")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "link .gemini/skills/ai-engineering-collaboration", result.stdout
            )
            self.assertFalse((target / ".gemini").exists())
            self.assertFalse((target / ".agents").exists())

    def test_project_conflicting_gemini_entry_aborts_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            conflicting_entry = (
                target / ".gemini" / "skills" / "ai-engineering-collaboration"
            )
            conflicting_entry.mkdir(parents=True)
            (conflicting_entry / "SKILL.md").write_text("modified\n", encoding="utf-8")

            result = self.run_script("--target", str(target))

            self.assertEqual(result.returncode, 2)
            self.assertIn("not a managed Gemini link", result.stderr)
            self.assertFalse((target / ".agents").exists())
            self.assertFalse((target / "AGENTS.md").exists())

    def test_project_identical_gemini_copy_is_left_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            existing_copy = target / ".gemini" / "skills" / "ci-triage"
            existing_copy.mkdir(parents=True)
            shutil.copytree(
                REPOSITORY_ROOT / "skills" / "ci-triage", existing_copy, dirs_exist_ok=True
            )

            result = self.run_script("--target", str(target))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(existing_copy.is_symlink())
            self.assertTrue(existing_copy.is_dir())
            self.assertIn("Gemini: 9 linked, 1 already current", result.stdout)

    def test_user_scope_links_skills_for_gemini_under_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            environment = dict(os.environ, HOME=str(home))

            first = self.run_script("--scope", "user", environment=environment)
            self.assertEqual(first.returncode, 0, first.stderr)
            for name in SOURCE_SKILLS:
                link = home / ".gemini" / "skills" / name
                self.assertTrue(link.is_symlink(), link)
                self.assertEqual(
                    link.resolve(), (home / ".agents" / "skills" / name).resolve()
                )
            self.assertFalse((home / "AGENTS.md").exists())

            second = self.run_script("--scope", "user", environment=environment)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn(
                f"Gemini Skills: 0 linked, {len(SOURCE_SKILLS)} already current.",
                second.stdout,
            )

    def test_user_scope_dry_run_reports_gemini_links_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            environment = dict(os.environ, HOME=str(home))

            result = self.run_script(
                "--scope", "user", "--dry-run", environment=environment
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                f"link {home / '.gemini' / 'skills' / 'ai-engineering-collaboration'}",
                result.stdout,
            )
            self.assertIn("Gemini link directory:", result.stdout)
            self.assertFalse((home / ".gemini").exists())
            self.assertFalse((home / ".agents").exists())

    def test_gemini_link_failure_reports_remedy_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            gemini_skills = target / ".gemini" / "skills"
            gemini_skills.mkdir(parents=True)
            gemini_skills.chmod(0o555)
            try:
                result = self.run_script("--target", str(target))
            finally:
                gemini_skills.chmod(0o755)

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("Failed to create Gemini link", result.stderr)
            self.assertIn("rerun", result.stderr)
            self.assertTrue(
                (target / ".agents" / "skills" / "ci-triage" / "SKILL.md").exists()
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
