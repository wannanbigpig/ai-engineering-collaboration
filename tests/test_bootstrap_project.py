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
            self.assertIn("Only with a usable `.codegraph/` index", agents_after_first)
            self.assertIn("never run `codegraph init` automatically", agents_after_first)
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

    def test_gitignore_history_mentions_do_not_count_as_removed_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory)
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            gitignore = target / ".gitignore"
            gitignore.write_text("foo.aitasks-cache\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(target), "add", ".gitignore"], check=True)
            subprocess.run(
                ["git", "-C", str(target), "-c", "user.name=Test", "-c",
                 "user.email=test@example.invalid", "commit", "-qm", "mention .aitasks"],
                check=True,
            )

            first = self.run_script("--target", str(target), "--dry-run")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("update .gitignore", first.stdout)

            gitignore.write_text("*.log\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(target), "add", ".gitignore"], check=True)
            subprocess.run(
                ["git", "-C", str(target), "-c", "user.name=Test", "-c",
                 "user.email=test@example.invalid", "commit", "-qm", "remove cache pattern"],
                check=True,
            )

            second = self.run_script("--target", str(target), "--dry-run")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("update .gitignore", second.stdout)

    def test_gitignore_history_keeps_intentionally_removed_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory)
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            gitignore = target / ".gitignore"
            for content, message in ((".aitasks/\n", "add rule"), ("*.log\n", "remove rule")):
                gitignore.write_text(content, encoding="utf-8")
                subprocess.run(["git", "-C", str(target), "add", ".gitignore"], check=True)
                subprocess.run(
                    ["git", "-C", str(target), "-c", "user.name=Test", "-c",
                     "user.email=test@example.invalid", "commit", "-qm", message],
                    check=True,
                )

            result = self.run_script("--target", str(target), "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("leave .gitignore unchanged", result.stdout)
            self.assertNotIn("update .gitignore", result.stdout)

    def test_track_aitasks_does_not_inspect_gitignore_symlink(self) -> None:
        for extra in (("--dry-run",), ()):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                gitignore = target / ".gitignore"
                gitignore.symlink_to("missing-config")

                result = self.run_script("--target", str(target), "--track-aitasks", *extra)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(gitignore.is_symlink())
                self.assertEqual(gitignore.readlink(), Path("missing-config"))
                self.assertFalse((target / "missing-config").exists())
                if not extra:
                    self.assertIn(".gitignore: no change required", result.stdout)

    def test_prints_custom_instructions_without_a_target(self) -> None:
        result = self.run_script("--print-custom-instructions")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Engineering defaults", result.stdout)
        self.assertIn("使用中文回复", result.stdout)
        self.assertIn("`.codegraph/`", result.stdout)
        self.assertIn("`codegraph status`", result.stdout)
        self.assertIn("不自动执行 `codegraph init`", result.stdout)

        documentation = (REPOSITORY_ROOT / "docs" / "project-bootstrap.md").read_text(
            encoding="utf-8"
        )
        custom_section = documentation.split("## Codex Custom Instructions", 1)[1]
        documented_instructions = custom_section.split("```md\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(result.stdout.strip(), documented_instructions.strip())

    def test_prints_custom_instructions_then_installs_user_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            environment = dict(os.environ, HOME=str(home))

            result = self.run_script(
                "--scope", "user", "--print-custom-instructions", environment=environment
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("# Engineering defaults", result.stdout)
            self.assertIn(f"User Skills: {len(SOURCE_SKILLS)} installed", result.stdout)
            self.assertEqual(
                sorted(path.name for path in (home / ".agents" / "skills").iterdir()),
                SOURCE_SKILLS,
            )
            self.assertFalse((home / "AGENTS.md").exists())

    def test_prints_custom_instructions_then_installs_project_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            target.mkdir()

            result = self.run_script(
                "--target", str(target), "--print-custom-instructions"
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("# Engineering defaults", result.stdout)
            self.assertIn(f"Skills: {len(SOURCE_SKILLS)} installed", result.stdout)
            self.assertTrue((target / "AGENTS.md").is_file())

    def test_generated_guidance_scopes_orchestration_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            target.mkdir()

            installed = self.run_script("--target", str(target))
            custom = self.run_script("--print-custom-instructions")

            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(custom.returncode, 0, custom.stderr)
            agents = (target / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("needs coordination across multiple specialist stages", agents)
            self.assertIn("For every project-code editing task, use `aitasks-maintenance`", agents)
            self.assertIn("Record a lesson immediately when the user explicitly asks", agents)
            self.assertNotIn("For non-trivial engineering work", agents)
            self.assertIn("确需跨多个专项阶段统筹", custom.stdout)
            self.assertIn("编辑项目代码时，不论是否使用入口 Skill", custom.stdout)
            self.assertIn("用户明确要求记录经验时立即记录", custom.stdout)
            self.assertIn("`AGENTS.override.md`", custom.stdout)
            self.assertNotIn("对非平凡工程任务", custom.stdout)
            self.assertIn("按风险执行最小必要验证", custom.stdout)
            self.assertIn("不为纯文档变更运行无关测试", custom.stdout)

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

    def test_project_target_links_skills_for_supported_harnesses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            target.mkdir()

            first = self.run_script("--target", str(target))
            self.assertEqual(first.returncode, 0, first.stderr)
            for harness, directory in (
                ("Gemini", ".gemini"),
                ("Claude Code", ".claude"),
                ("ZCode", ".zcode"),
            ):
                with self.subTest(harness=harness):
                    harness_skills = target / directory / "skills"
                    self.assertEqual(
                        sorted(path.name for path in harness_skills.iterdir()), SOURCE_SKILLS
                    )
                    for name in SOURCE_SKILLS:
                        link = harness_skills / name
                        self.assertTrue(link.is_symlink(), link)
                        self.assertEqual(
                            link.resolve(), (target / ".agents" / "skills" / name).resolve()
                        )
                    self.assertIn(
                        f"{harness}: {len(SOURCE_SKILLS)} linked, 0 already current",
                        first.stdout,
                    )

            second = self.run_script("--target", str(target))
            self.assertEqual(second.returncode, 0, second.stderr)
            for harness in ("Gemini", "Claude Code", "ZCode"):
                self.assertIn(
                    f"{harness}: 0 linked, {len(SOURCE_SKILLS)} already current",
                    second.stdout,
                )

    def test_project_dry_run_reports_gemini_links_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            target.mkdir()

            result = self.run_script("--target", str(target), "--dry-run")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("link .gemini/skills/ai-engineering-collaboration", result.stdout)
            self.assertIn("link .claude/skills/ai-engineering-collaboration", result.stdout)
            self.assertIn("link .zcode/skills/ai-engineering-collaboration", result.stdout)
            self.assertFalse((target / ".gemini").exists())
            self.assertFalse((target / ".claude").exists())
            self.assertFalse((target / ".zcode").exists())
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

    def test_user_scope_links_skills_for_supported_harnesses_under_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            environment = dict(os.environ, HOME=str(home))

            first = self.run_script("--scope", "user", environment=environment)
            self.assertEqual(first.returncode, 0, first.stderr)
            for harness, directory in (
                ("Gemini", ".gemini"),
                ("Claude Code", ".claude"),
                ("ZCode", ".zcode"),
            ):
                with self.subTest(harness=harness):
                    for name in SOURCE_SKILLS:
                        link = home / directory / "skills" / name
                        self.assertTrue(link.is_symlink(), link)
                        self.assertEqual(
                            link.resolve(), (home / ".agents" / "skills" / name).resolve()
                        )
            self.assertFalse((home / "AGENTS.md").exists())

            second = self.run_script("--scope", "user", environment=environment)
            self.assertEqual(second.returncode, 0, second.stderr)
            for harness in ("Gemini", "Claude Code", "ZCode"):
                self.assertIn(
                    f"{harness} Skills: 0 linked, {len(SOURCE_SKILLS)} already current.",
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
            self.assertIn(
                f"link {home / '.claude' / 'skills' / 'ai-engineering-collaboration'}",
                result.stdout,
            )
            self.assertIn(
                f"link {home / '.zcode' / 'skills' / 'ai-engineering-collaboration'}",
                result.stdout,
            )
            self.assertIn("Gemini link directory:", result.stdout)
            self.assertIn("Claude Code link directory:", result.stdout)
            self.assertIn("ZCode link directory:", result.stdout)
            self.assertFalse((home / ".gemini").exists())
            self.assertFalse((home / ".claude").exists())
            self.assertFalse((home / ".zcode").exists())
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

    def test_dangling_config_links_fail_before_any_installation(self) -> None:
        for name in ("AGENTS.md", ".gitignore"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                link = target / name
                link.symlink_to("missing-config")
                for extra in (("--dry-run",), ()):
                    result = self.run_script("--target", str(target), *extra)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("Expected a regular file", result.stderr)
                    self.assertTrue(link.is_symlink())
                    self.assertEqual(link.readlink(), Path("missing-config"))
                    self.assertEqual(list(target.iterdir()), [link])

    def test_dangling_skill_link_is_a_preflight_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            skills = target / ".agents" / "skills"
            skills.mkdir(parents=True)
            dangling = skills / "aitasks-maintenance"
            dangling.symlink_to("missing-skill")

            result = self.run_script("--target", str(target))

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("exists but is not a directory", result.stderr)
            self.assertTrue(dangling.is_symlink())
            self.assertEqual(list(skills.iterdir()), [dangling])
            self.assertFalse((target / "AGENTS.md").exists())

    def test_dangling_skills_directory_fails_before_other_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            agents = target / ".agents"
            agents.mkdir(parents=True)
            (agents / "skills").symlink_to("missing-skills")

            result = self.run_script("--target", str(target))

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("Expected a directory", result.stderr)
            self.assertEqual(list(agents.iterdir()), [agents / "skills"])
            self.assertFalse((target / "AGENTS.md").exists())


if __name__ == "__main__":
    unittest.main()
