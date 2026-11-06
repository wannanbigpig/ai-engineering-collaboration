from __future__ import annotations

import os
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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

    def test_unmanaged_agents_content_and_mode_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            agents = target / "AGENTS.md"
            original = b"# Existing rules\r\nA hard break  \r\n\r\n"
            agents.write_bytes(original)
            agents.chmod(0o640)

            first = self.run_script("--target", str(target))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(agents.read_bytes().startswith(original))
            self.assertEqual(agents.stat().st_mode & 0o777, 0o640)
            self.assertIn(b"<!-- ai-engineering-collaboration:begin -->\r\n", agents.read_bytes())
            installed = agents.read_bytes()
            second = self.run_script("--target", str(target))
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(agents.read_bytes(), installed)
            self.assertEqual(agents.stat().st_mode & 0o777, 0o640)

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

    def test_check_reports_missing_current_and_different_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            missing = self.run_script("--target", str(target), "--check")
            self.assertEqual(missing.returncode, 1, missing.stderr)
            self.assertIn("missing", missing.stdout)
            self.assertEqual(list(target.iterdir()), [])
            installed = self.run_script("--target", str(target))
            self.assertEqual(installed.returncode, 0, installed.stderr)
            current = self.run_script("--target", str(target), "--check")
            self.assertEqual(current.returncode, 0, current.stderr)
            skill = target / ".agents/skills/ci-triage/SKILL.md"
            skill.write_text(skill.read_text() + "\nUser customization.\n")
            original = skill.read_bytes()
            different = self.run_script("--target", str(target), "--check")
            self.assertEqual(different.returncode, 1, different.stderr)
            self.assertIn("different", different.stdout)
            self.assertEqual(skill.read_bytes(), original)
            skill.write_bytes((REPOSITORY_ROOT / "skills/ci-triage/SKILL.md").read_bytes())
            skill.chmod(0o600)
            mode_only = self.run_script("--target", str(target), "--check")
            self.assertEqual(mode_only.returncode, 1, mode_only.stderr)
            self.assertEqual(skill.stat().st_mode & 0o777, 0o600)

    def test_distribution_ignores_generated_files_but_preserves_customizations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            shutil.copytree(REPOSITORY_ROOT / "skills", source / "skills")
            (source / "scripts").mkdir()
            shutil.copy2(SCRIPT, source / "scripts/bootstrap_project.py")
            tool = source / "skills/aitasks-maintenance/scripts/maintain_aitasks.py"
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            subprocess.run(
                [sys.executable, "-c", "import py_compile,sys; sys.pycache_prefix=None; py_compile.compile(sys.argv[1], doraise=True)", str(tool)],
                env=environment, check=True, capture_output=True,
            )
            cache = tool.parent / "__pycache__"
            self.assertTrue(any(cache.glob("*.pyc")))
            (tool.parent / "leftover.pyc").write_bytes(b"compiled artifact")
            (tool.parent / ".DS_Store").write_bytes(b"finder metadata")
            (tool.parent / "cache-policy.md").write_text("A real distributed resource.\n")
            target = root / "project"
            target.mkdir()
            command = [sys.executable, "-B", str(source / "scripts/bootstrap_project.py"), "--target", str(target)]

            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = target / ".agents/skills/aitasks-maintenance/scripts"
            self.assertFalse((installed / "__pycache__").exists())
            self.assertFalse((installed / "leftover.pyc").exists())
            self.assertFalse((installed / ".DS_Store").exists())
            self.assertEqual((installed / "cache-policy.md").read_text(), "A real distributed resource.\n")

            shutil.rmtree(cache)
            (tool.parent / "leftover.pyc").unlink()
            (tool.parent / ".DS_Store").unlink()
            (installed / "__pycache__").mkdir()
            (installed / "__pycache__/local.pyc").write_bytes(b"local generated cache")
            check = subprocess.run(command + ["--check"], capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stderr)
            (installed / "custom.md").write_text("User customization.\n")
            check = subprocess.run(command + ["--check"], capture_output=True, text=True)
            self.assertEqual(check.returncode, 1, check.stderr)
            reinstall = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(reinstall.returncode, 2, reinstall.stderr)
            self.assertEqual((installed / "custom.md").read_text(), "User customization.\n")

    def test_check_json_reports_versions_paths_and_compatibility_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            missing = self.run_script("--target", str(target), "--check", "--json")
            self.assertEqual(missing.returncode, 1, missing.stderr)
            report = json.loads(missing.stdout)
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["scope"], "project")
            self.assertFalse(report["current"])
            self.assertTrue(all(skill["status"] == "missing" for skill in report["skills"]))
            self.assertEqual(list(target.iterdir()), [])
            installed = self.run_script("--target", str(target))
            self.assertEqual(installed.returncode, 0, installed.stderr)

            current = self.run_script("--target", str(target), "--check", "--json")
            self.assertEqual(current.returncode, 0, current.stderr)
            report = json.loads(current.stdout)
            self.assertTrue(report["current"])
            skill = next(row for row in report["skills"] if row["name"] == "ci-triage")
            self.assertEqual(skill["source"]["version"], (REPOSITORY_ROOT / "VERSION").read_text().strip())
            self.assertEqual(skill["installed"]["version"], skill["source"]["version"])
            self.assertEqual(skill["source"]["manifest_sha256"], skill["installed"]["manifest_sha256"])
            self.assertEqual(skill["installed"]["path"], str(target.resolve() / ".agents/skills/ci-triage"))
            self.assertEqual(skill["installed"]["resolved_path"], str((target / ".agents/skills/ci-triage").resolve()))
            self.assertTrue(all(link["kind"] == "symlink" and link["status"] == "current" for link in skill["compatibility"]))

            customization = target / ".agents/skills/ci-triage/SKILL.md"
            customization.write_text(customization.read_text() + "\nUser customization.\n")
            compatibility = target / ".claude/skills/ci-triage"
            compatibility.unlink()
            before = customization.read_bytes()
            different = self.run_script("--target", str(target), "--check", "--json")
            self.assertEqual(different.returncode, 1, different.stderr)
            report = json.loads(different.stdout)
            skill = next(row for row in report["skills"] if row["name"] == "ci-triage")
            self.assertEqual(skill["status"], "different")
            self.assertNotEqual(skill["source"]["manifest_sha256"], skill["installed"]["manifest_sha256"])
            self.assertEqual(next(link for link in skill["compatibility"] if link["harness"] == "Claude Code")["status"], "missing")
            self.assertEqual(customization.read_bytes(), before)
            self.assertFalse(compatibility.exists())

    def test_json_requires_check_and_cannot_mix_custom_instruction_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for extra in (("--json",), ("--check", "--json", "--print-custom-instructions")):
                with self.subTest(arguments=extra):
                    result = self.run_script("--target", directory, *extra)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(list(Path(directory).iterdir()), [])

    def test_check_json_user_scope_and_invalid_content_are_readonly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            environment = dict(os.environ, HOME=str(target))
            installed = self.run_script("--scope", "user", environment=environment)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            current = self.run_script("--scope", "user", "--check", "--json", environment=environment)
            self.assertEqual(current.returncode, 0, current.stderr)
            self.assertEqual(json.loads(current.stdout)["scope"], "user")
            link = target / ".agents/skills/ci-triage/custom-link.md"
            link.symlink_to(target / "outside.md")
            invalid = self.run_script("--scope", "user", "--check", "--json", environment=environment)
            self.assertEqual(invalid.returncode, 1, invalid.stderr)
            report = json.loads(invalid.stdout)
            self.assertFalse(report["current"])
            self.assertIn("Symlinked skill content is unsupported", report["error"])
            self.assertTrue(link.is_symlink())
            self.assertFalse((target / "AGENTS.md").exists())

    def test_upgrade_ignores_installed_cache_but_not_additional_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "old release"
            shutil.copytree(REPOSITORY_ROOT / "skills", baseline / "skills")
            old = baseline / "skills/ci-triage/SKILL.md"
            old.write_text(old.read_text() + "\nOld release content.\n")
            target = root / "project"
            shutil.copytree(baseline / "skills", target / ".agents/skills")
            cache = target / ".agents/skills/ci-triage/__pycache__"
            cache.mkdir()
            (cache / "local.pyc").write_bytes(b"local cache")
            customization = target / ".agents/skills/ci-triage/custom.md"
            customization.write_text("Keep my addition.\n")
            command = ("--target", str(target), "--upgrade-from", str(baseline))
            refused = self.run_script(*command)
            self.assertEqual(refused.returncode, 2, refused.stderr)
            self.assertTrue(customization.exists())
            customization.unlink()
            upgraded = self.run_script(*command)
            self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
            self.assertEqual(self.run_script("--target", str(target), "--check").returncode, 0)
            self.assertFalse(cache.exists())

    def test_source_resource_symlink_fails_before_installing_any_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            shutil.copytree(REPOSITORY_ROOT / "skills", source / "skills")
            (source / "scripts").mkdir()
            shutil.copy2(SCRIPT, source / "scripts/bootstrap_project.py")
            external = root / "external.md"
            external.write_text("Do not distribute.\n")
            (source / "skills/verification-gate/external.md").symlink_to(external)
            target = root / "project"
            target.mkdir()
            result = subprocess.run(
                [sys.executable, "-B", str(source / "scripts/bootstrap_project.py"), "--target", str(target)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("Symlinked skill content is unsupported", result.stderr)
            self.assertEqual(list(target.iterdir()), [])

    def test_explicit_upgrade_replaces_only_baseline_matched_copies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "old release"
            shutil.copytree(REPOSITORY_ROOT / "skills", baseline / "skills")
            old = baseline / "skills/ci-triage"
            old_skill = old / "SKILL.md"
            old_skill.write_text(old_skill.read_text() + "\nOld release content.\n")
            (old / "removed-in-new-release.txt").write_text("Old managed resource")
            target = root / "project"
            shutil.copytree(baseline / "skills", target / ".agents/skills")
            compatibility = target / ".claude/skills/ci-triage"
            shutil.copytree(old, compatibility)
            agents = target / "AGENTS.md"
            agents.write_text("# User project rules\n")
            preview = self.run_script("--target", str(target), "--upgrade-from", str(baseline), "--dry-run")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("upgrade ci-triage", preview.stdout)
            self.assertTrue((target / ".agents/skills/ci-triage/removed-in-new-release.txt").exists())
            result = self.run_script("--target", str(target), "--upgrade-from", str(baseline))
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = (REPOSITORY_ROOT / "skills/ci-triage/SKILL.md").read_bytes()
            self.assertEqual((target / ".agents/skills/ci-triage/SKILL.md").read_bytes(), expected)
            self.assertEqual((compatibility / "SKILL.md").read_bytes(), expected)
            self.assertFalse((compatibility / "removed-in-new-release.txt").exists())
            self.assertFalse((target / ".agents/skills/ci-triage/removed-in-new-release.txt").exists())
            self.assertTrue(agents.read_text().startswith("# User project rules\n"))
            self.assertEqual(self.run_script("--target", str(target), "--check").returncode, 0)

    def test_upgrade_installs_skill_added_after_the_old_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "previous release"
            shutil.copytree(REPOSITORY_ROOT / "skills", baseline / "skills")
            shutil.rmtree(baseline / "skills/frontend-ui-ux")
            current_version = (REPOSITORY_ROOT / "VERSION").read_text().strip()
            for skill in (baseline / "skills").glob("*/SKILL.md"):
                content = skill.read_text(encoding="utf-8")
                old_content = content.replace(f"  version: {current_version}\n", "  version: 0.0.0\n", 1)
                self.assertNotEqual(old_content, content)
                skill.write_text(old_content, encoding="utf-8")

            target = root / "project"
            shutil.copytree(baseline / "skills", target / ".agents/skills")
            new_skill = target / ".agents/skills/frontend-ui-ux"
            arguments = ("--target", str(target), "--upgrade-from", str(baseline))

            preview = self.run_script(*arguments, "--dry-run")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("install frontend-ui-ux", preview.stdout)
            self.assertFalse(new_skill.exists())

            installed = self.run_script(*arguments)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(
                (new_skill / "SKILL.md").read_bytes(),
                (REPOSITORY_ROOT / "skills/frontend-ui-ux/SKILL.md").read_bytes(),
            )
            for harness in (".claude", ".gemini", ".zcode"):
                link = target / harness / "skills/frontend-ui-ux"
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), new_skill.resolve())
            check = self.run_script("--target", str(target), "--check")
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_upgrade_refuses_customized_copy_before_any_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline"
            shutil.copytree(REPOSITORY_ROOT / "skills", baseline / "skills")
            old = baseline / "skills/ci-triage/SKILL.md"
            old.write_text(old.read_text() + "\nOld release\n")
            target = root / "project"
            shutil.copytree(baseline / "skills", target / ".agents/skills")
            changed = target / ".agents/skills/code-review/SKILL.md"
            changed.write_text(changed.read_text() + "\nUser customization\n")
            before = {str(p.relative_to(target)): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            result = self.run_script("--target", str(target), "--upgrade-from", str(baseline))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("differs", result.stderr)
            after = {str(p.relative_to(target)): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            self.assertEqual(after, before)

    def test_user_scope_check_and_upgrade_only_touch_skill_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline"
            shutil.copytree(REPOSITORY_ROOT / "skills", baseline / "skills")
            old = baseline / "skills/ci-triage/SKILL.md"
            old.write_text(old.read_text() + "\nOld release\n")
            home = root / "home"
            shutil.copytree(baseline / "skills", home / ".agents/skills")
            environment = dict(os.environ, HOME=str(home))
            before = {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}
            check = self.run_script("--scope", "user", "--check", environment=environment)
            self.assertEqual(check.returncode, 1, check.stderr)
            self.assertEqual(before, {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()})
            upgrade = self.run_script("--scope", "user", "--upgrade-from", str(baseline), environment=environment)
            self.assertEqual(upgrade.returncode, 0, upgrade.stderr)
            self.assertEqual(self.run_script("--scope", "user", "--check", environment=environment).returncode, 0)
            self.assertFalse((home / "AGENTS.md").exists())
            self.assertFalse((home / ".gitignore").exists())

    def test_upgrade_restores_previous_copy_when_replacement_fails(self) -> None:
        spec = importlib.util.spec_from_file_location("bootstrap_upgrade", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source/skill"
            destination = root / "installed/skill"
            source.mkdir(parents=True)
            destination.mkdir(parents=True)
            (source / "SKILL.md").write_text("new")
            (destination / "SKILL.md").write_text("old")
            replace = Path.replace
            def fail_new(path, target):
                if path.name == "new":
                    raise OSError("injected replacement failure")
                return replace(path, target)
            with mock.patch.object(Path, "replace", fail_new):
                with self.assertRaises(module.BootstrapError):
                    module.copy_skills([source], destination.parent)
            self.assertEqual((destination / "SKILL.md").read_text(), "old")
            self.assertEqual(list(destination.parent.iterdir()), [destination])

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

    def test_gitignore_append_preserves_escaped_trailing_space(self) -> None:
        for newline in (b"\n", b"\r\n"):
            with self.subTest(newline=newline), tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                subprocess.run(["git", "init", "-q", str(target)], check=True)
                original = b"file\\ " + newline
                gitignore = target / ".gitignore"
                gitignore.write_bytes(original)
                gitignore.chmod(0o640)
                (target / "file ").touch()
                before = subprocess.run(
                    ["git", "-C", str(target), "check-ignore", "--quiet", "--", "file "],
                    check=False,
                )
                self.assertEqual(before.returncode, 0)

                result = self.run_script("--target", str(target))

                self.assertEqual(result.returncode, 0, result.stderr)
                updated = gitignore.read_bytes()
                self.assertTrue(updated.startswith(original))
                self.assertIn(b".aitasks/" + newline, updated)
                self.assertEqual(gitignore.stat().st_mode & 0o777, 0o640)
                after = subprocess.run(
                    ["git", "-C", str(target), "check-ignore", "--quiet", "--", "file "],
                    check=False,
                )
                self.assertEqual(after.returncode, 0)

    def test_missing_git_preserves_ignore_rules_but_installs_skills(self) -> None:
        for is_git_project in (False, True):
            with self.subTest(is_git_project=is_git_project), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "project"
                target.mkdir()
                if is_git_project:
                    subprocess.run(["git", "init", "-q", str(target)], check=True)
                gitignore = target / ".gitignore"
                gitignore.write_text("existing-pattern\n", encoding="utf-8")
                empty_path = Path(directory) / "empty-path"
                empty_path.mkdir()
                environment = dict(os.environ, PATH=str(empty_path))

                preview = self.run_script("--target", str(target), "--dry-run", environment=environment)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                self.assertIn("leave .gitignore unchanged", preview.stdout)
                self.assertIn("Git", preview.stdout)
                self.assertFalse((target / ".agents").exists())

                result = self.run_script("--target", str(target), environment=environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(gitignore.read_text(encoding="utf-8"), "existing-pattern\n")
                self.assertIn(".gitignore: unchanged", result.stdout)
                self.assertIn("Git", result.stdout)
                self.assertTrue((target / ".agents" / "skills" / "code-review" / "SKILL.md").is_file())

    def test_missing_git_does_not_create_ignore_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "project"
            target.mkdir()
            empty_path = Path(directory) / "empty-path"
            empty_path.mkdir()
            environment = dict(os.environ, PATH=str(empty_path))

            result = self.run_script("--target", str(target), environment=environment)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((target / ".gitignore").exists())
            self.assertIn("Git", result.stdout)
            self.assertTrue((target / ".agents" / "skills" / "code-review" / "SKILL.md").is_file())

    def test_user_scope_checks_home_path_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home_file = Path(directory) / "home"
            home_file.write_text("not a directory", encoding="utf-8")
            environment = dict(os.environ, HOME=str(home_file))

            for extra in (("--dry-run",), ()):
                result = self.run_script("--scope", "user", *extra, environment=environment)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Expected a directory", result.stderr)
                self.assertEqual(home_file.read_text(encoding="utf-8"), "not a directory")

    def test_git_inspection_failure_leaves_ignore_file_unchanged(self) -> None:
        for failure in ("repository", "unexpected", "tracked", "history"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "project"
                target.mkdir()
                gitignore = target / ".gitignore"
                gitignore.write_text("existing-pattern\n", encoding="utf-8")
                fake_bin = Path(directory) / "bin"
                fake_bin.mkdir()
                fake_git = fake_bin / "git"
                fake_git.write_text(
                    '#!/bin/sh\n'
                    f'failure={failure}\n'
                    'case "$*" in\n'
                    '  *"rev-parse --is-inside-work-tree"*)\n'
                    '    if [ "$failure" = repository ]; then echo "permission denied" >&2; exit 1; fi\n'
                    '    if [ "$failure" != unexpected ]; then echo true; fi ;;\n'
                    '  *"ls-files"*) if [ "$failure" = tracked ]; then exit 1; fi ;;\n'
                    '  *"log"*) if [ "$failure" = history ]; then exit 1; fi ;;\n'
                    '  *"rev-list"*) echo existing-ref ;;\n'
                    'esac\n',
                    encoding="utf-8",
                )
                fake_git.chmod(0o755)
                environment = dict(os.environ, PATH=str(fake_bin))

                result = self.run_script("--target", str(target), environment=environment)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(gitignore.read_text(encoding="utf-8"), "existing-pattern\n")
                self.assertIn(".gitignore: unchanged", result.stdout)
                self.assertIn("could not be checked", result.stdout)

    def test_broken_git_marker_preserves_ignore_file(self) -> None:
        for marker_location in ("target", "ancestor"):
            for marker_kind in ("gitdir_file", "dangling_link", "invalid_dir"):
                with self.subTest(location=marker_location, kind=marker_kind), tempfile.TemporaryDirectory() as directory:
                    base = Path(directory) / "project"
                    target = base / "nested" if marker_location == "ancestor" else base
                    target.mkdir(parents=True)
                    marker = (base if marker_location == "ancestor" else target) / ".git"
                    if marker_kind == "gitdir_file":
                        marker.write_text("gitdir: /missing-test-gitdir\n", encoding="utf-8")
                    elif marker_kind == "dangling_link":
                        marker.symlink_to("missing-gitdir")
                    else:
                        marker.mkdir()
                    gitignore = target / ".gitignore"
                    gitignore.write_text("existing-pattern\n", encoding="utf-8")
                    environment = dict(os.environ)
                    environment.pop("GIT_DIR", None)

                    result = self.run_script("--target", str(target), environment=environment)

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(gitignore.read_text(encoding="utf-8"), "existing-pattern\n")
                    self.assertIn(".gitignore: unchanged", result.stdout)
                    self.assertIn("could not be checked", result.stdout)
                    self.assertTrue((target / ".agents" / "skills" / "code-review" / "SKILL.md").is_file())

    def test_broken_git_dir_environment_preserves_ignore_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "project"
            target.mkdir()
            gitignore = target / ".gitignore"
            gitignore.write_text("existing-pattern\n", encoding="utf-8")
            environment = dict(os.environ, GIT_DIR=str(Path(directory) / "missing-gitdir"))

            result = self.run_script("--target", str(target), environment=environment)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(gitignore.read_text(encoding="utf-8"), "existing-pattern\n")
            self.assertIn(".gitignore: unchanged", result.stdout)
            self.assertIn("could not be checked", result.stdout)

    def test_non_git_directory_still_receives_ignore_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "project"
            target.mkdir()
            environment = dict(os.environ)
            environment.pop("GIT_DIR", None)

            result = self.run_script("--target", str(target), environment=environment)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(".aitasks/", (target / ".gitignore").read_text(encoding="utf-8"))

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
        self.assertIn("不默认整篇加载或更新计数", result.stdout)
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

    def test_installed_maintenance_cli_supports_task_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project"
            target.mkdir()

            installed = self.run_script("--target", str(target))
            self.assertEqual(installed.returncode, 0, installed.stderr)
            (target / ".aitasks").mkdir()
            tool = target / ".agents/skills/aitasks-maintenance/scripts/maintain_aitasks.py"
            command = [sys.executable, "-B", str(tool), "--project-root", str(target)]
            subprocess.run(command + ["add-todo", "--title", "Installed task", "--goal", "Fix behavior",
                                     "--verify", "Regression", "--maintain"], check=True, capture_output=True)
            completed = subprocess.run(command + ["finish-todo", "--todo", "Installed task", "--result", "Verified"],
                                       check=True, capture_output=True)
            text = (target / ".aitasks/todo.md").read_text()
            self.assertIn("status=completed", text)
            self.assertIn("Verified", text)
            self.assertNotIn("待完成", text)
            self.assertIn(b"Maintenance not due", completed.stdout)

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
            self.assertIn(f"Gemini: {len(SOURCE_SKILLS) - 1} linked, 1 already current", result.stdout)

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

    def test_link_parent_file_or_dangling_link_fails_before_writes(self) -> None:
        for scope in ("project", "user"):
            for parent in (".agents", ".gemini"):
                for dangling in (False, True):
                    with self.subTest(scope=scope, parent=parent, dangling=dangling), tempfile.TemporaryDirectory() as directory:
                        target = Path(directory) / "target"
                        target.mkdir()
                        blocked = target / parent
                        if dangling:
                            blocked.symlink_to("missing")
                        else:
                            blocked.write_text("existing", encoding="utf-8")
                        arguments = ("--target", str(target)) if scope == "project" else ("--scope", "user")
                        environment = dict(os.environ, HOME=str(target))

                        for extra in (("--dry-run",), ()):
                            result = self.run_script(*arguments, *extra, environment=environment)
                            self.assertEqual(result.returncode, 1, result.stderr)
                            self.assertIn("Expected a directory", result.stderr)
                            self.assertEqual(list(target.iterdir()), [blocked])
                            if dangling:
                                self.assertTrue(blocked.is_symlink())
                            else:
                                self.assertEqual(blocked.read_text(encoding="utf-8"), "existing")

    def test_redirected_compatibility_parent_links_to_canonical_skills(self) -> None:
        for scope in ("project", "user"):
            for symlink_level in ("parent", "skills"):
                with self.subTest(scope=scope, symlink_level=symlink_level), tempfile.TemporaryDirectory() as directory:
                    target = Path(directory) / "target"
                    target.mkdir()
                    external = Path(directory) / "external-config"
                    external.mkdir()
                    if symlink_level == "parent":
                        (target / ".gemini").symlink_to(external, target_is_directory=True)
                    else:
                        (target / ".gemini").mkdir()
                        (target / ".gemini" / "skills").symlink_to(external, target_is_directory=True)
                    arguments = ("--target", str(target)) if scope == "project" else ("--scope", "user")
                    environment = dict(os.environ, HOME=str(target))

                    preview = self.run_script(*arguments, "--dry-run", environment=environment)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    self.assertFalse((target / ".agents").exists())
                    self.assertEqual(list(external.iterdir()), [])

                    first = self.run_script(*arguments, environment=environment)
                    self.assertEqual(first.returncode, 0, first.stderr)
                    link = target / ".gemini" / "skills" / "code-review"
                    canonical = target / ".agents" / "skills" / "code-review"
                    self.assertTrue(link.is_symlink())
                    self.assertTrue(link.is_dir())
                    self.assertEqual(link.resolve(), canonical.resolve())
                    self.assertEqual(os.readlink(link), os.path.relpath(canonical.resolve(), link.parent.resolve()))
                    second = self.run_script(*arguments, environment=environment)
                    self.assertEqual(second.returncode, 0, second.stderr)
                    self.assertIn("0 linked", second.stdout)

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
