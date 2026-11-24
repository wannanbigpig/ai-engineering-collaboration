import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SKILLS = Path(__file__).resolve().parents[1] / "skills"
IGNORE_PYTHON_CACHE = shutil.ignore_patterns("__pycache__", "*.pyc")
SKILLS_CLI = "skills@1.9.0"


def snapshot(directory):
    return {path.relative_to(directory): path.read_bytes() if path.is_file() else None
            for path in directory.rglob("*")}


class StandaloneSkillsTest(unittest.TestCase):
    def run_tool(self, script, project, *args):
        result = subprocess.run(
            [sys.executable, "-E", "-s", "-B", str(script), "--project-root", str(project), *args],
            cwd=project, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_each_consumer_queries_records_without_writing(self):
        for name in ("ai-engineering-collaboration", "code-review", "systematic-debugging", "change-impact-analysis"):
            with self.subTest(skill=name), tempfile.TemporaryDirectory() as temporary:
                isolated = Path(temporary)
                skill = shutil.copytree(SKILLS / name, isolated / name, ignore=IGNORE_PYTHON_CACHE)
                project = isolated / "project"
                records = project / ".aitasks"
                records.mkdir(parents=True)
                (records / "lessons.md").write_text(
                    "# Lessons\n\n## Legacy invoice\nKeep invoice formatting.\n\n"
                    "<!-- aitasks:lesson id=old status=retired -->\n## Old invoice\nINACTIVE_SENTINEL\n\n"
                    "<!-- aitasks:lesson id=current status=active -->\n## Current invoice\nInvoice format.\n\n"
                    "```markdown\n<!-- aitasks:lesson id=fake status=retired -->\n## Example\n```\n"
                    "CURRENT_END\n\n<!-- aitasks:lesson id=next status=active -->\n## Other\nNEXT_SENTINEL\n",
                    encoding="utf-8",
                )
                before = snapshot(isolated)
                query = skill / "scripts/query_aitasks.py"
                context = self.run_tool(query, project, "context", "--query", "invoice")
                summaries = context["lessons"]
                self.assertEqual(len(summaries), 2)
                self.assertIn("current", {row["id"] for row in summaries})
                self.assertNotIn("INACTIVE_SENTINEL", json.dumps(context))
                detail = self.run_tool(query, project, "get-record", "--kind", "lesson", "--id", "current")
                self.assertIn("CURRENT_END", detail["content"])
                self.assertNotIn("NEXT_SENTINEL", detail["content"])
                self.assertEqual(snapshot(isolated), before)
                self.assertFalse((skill / "scripts/maintain_aitasks.py").exists())

    def test_maintenance_can_create_and_finish_a_todo(self):
        with tempfile.TemporaryDirectory() as temporary:
            isolated = Path(temporary)
            skill = shutil.copytree(SKILLS / "aitasks-maintenance", isolated / "aitasks-maintenance",
                                   ignore=IGNORE_PYTHON_CACHE)
            project = isolated / "project"
            records = project / ".aitasks"
            records.mkdir(parents=True)
            maintain = skill / "scripts/maintain_aitasks.py"
            added = self.run_tool(maintain, project, "add-todo", "--title", "Standalone task",
                                  "--goal", "Fix behavior", "--verify", "Regression", "--maintain", "--json")
            completed = self.run_tool(maintain, project, "finish-todo", "--id", added["id"],
                                      "--result", "Verified", "--json")
            self.assertEqual(completed["status"], "completed")
            stored = (records / "todo.md").read_text(encoding="utf-8")
            self.assertIn(f'id={added["id"]}', stored)
            self.assertIn("status=completed", stored)
            self.assertIn("Verified", stored)
            self.assertNotIn("待完成", stored)


@unittest.skipUnless(os.environ.get("REQUIRE_NPX_INSTALL") == "1", "npx smoke requires Node.js and npm access")
class NpxInstallationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        home = self.root / "home"
        home.mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.lower().startswith(("git_", "npm_config_"))}
        self.env.update(
            HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(home / ".codex"),
            XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local/share"),
            XDG_CACHE_HOME=str(home / ".cache"), npm_config_cache=str(self.root / "npm-cache"),
            npm_config_userconfig=str(home / ".npmrc"), npm_config_globalconfig=str(home / "npm-global.rc"),
            DISABLE_TELEMETRY="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
            GIT_TERMINAL_PROMPT="0",
        )

    def run_command(self, *argv, cwd=None, status=0):
        result = subprocess.run(argv, cwd=cwd or self.project, env=self.env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, status, f"{argv}\n{result.stdout}\n{result.stderr}")
        return result.stdout

    def cli(self, *args, status=0):
        return self.run_command("npx", "--yes", SKILLS_CLI, *args, status=status)

    def installed(self):
        return {row["name"]: row for row in json.loads(self.cli("list", "--json"))}

    def lock(self):
        return json.loads((self.project / "skills-lock.json").read_text(encoding="utf-8"))["skills"]

    def test_local_install_contains_the_standalone_query_resources(self):
        self.cli("add", str(SKILLS.parent), "--skill", "code-review", "--agent", "codex", "-y")
        installed = self.project / ".agents/skills/code-review"
        rows = self.installed()
        self.assertEqual(set(rows), {"code-review"})
        self.assertEqual(rows["code-review"]["status"], "tracked")
        self.assertEqual(rows["code-review"]["sourceType"], "local")
        self.assertEqual(Path(rows["code-review"]["path"]).resolve(), installed)
        self.assertRegex(self.lock()["code-review"]["computedHash"], r"^[0-9a-f]{64}$")
        for name in ("SKILL.md", "scripts/query_aitasks.py", "assets/search-aliases.json"):
            self.assertEqual((installed / name).read_bytes(), (SKILLS / "code-review" / name).read_bytes())
        records = self.project / ".aitasks"
        records.mkdir()
        (records / "lessons.md").write_text("## Invoice format\nKeep decimals.\n", encoding="utf-8")
        before = snapshot(self.project)
        result = self.run_command(sys.executable, "-E", "-s", "-B", str(installed / "scripts/query_aitasks.py"),
                                  "--project-root", str(self.project), "context", "--query", "invoice")
        self.assertEqual([row["title"] for row in json.loads(result)["lessons"]], ["Invoice format"])
        self.assertEqual(snapshot(self.project), before)

    def test_git_update_keeps_unselected_local_customization(self):
        source = self.root / "upstream"
        source.mkdir()
        self.run_command("git", "init", "--quiet", cwd=source)
        custom_name, update_name = "local-custom", "update-target"
        for name in (custom_name, update_name):
            skill = source / "skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: An installation fixture.\n---\n\ninitial content\n",
                encoding="utf-8",
            )
        filtered = source / "skills" / update_name
        (filtered / "metadata.json").write_text("{}", encoding="utf-8")
        (filtered / "__pypackages__").mkdir()
        (filtered / "__pypackages__/example.py").write_text("# excluded\n", encoding="utf-8")

        def commit(message):
            self.run_command("git", "add", ".", cwd=source)
            self.run_command("git", "-c", "user.name=Skill Fixture", "-c", "user.email=fixture@example.invalid",
                             "commit", "--quiet", "-m", message, cwd=source)

        commit("initial skills")
        target = self.project / ".agents/skills"
        custom = target / custom_name
        custom.mkdir(parents=True)
        old_copy = custom / "SKILL.md"
        old_copy.write_bytes((source / "skills" / custom_name / "SKILL.md").read_bytes() + b"handwritten\n")
        self.assertEqual(self.installed()[custom_name]["status"], "untracked")
        backup = self.root / "backup"
        custom.rename(backup)

        self.cli("add", source.as_uri(), "--skill", custom_name, "--skill", update_name, "--agent", "codex", "-y")
        self.assertEqual({name: row["status"] for name, row in self.installed().items()},
                         {custom_name: "tracked", update_name: "tracked"})
        original_lock = self.lock()
        self.assertEqual(original_lock[update_name]["sourceType"], "git")
        self.assertEqual(original_lock[update_name]["sourceUrl"], source.as_uri())
        self.assertRegex(original_lock[update_name]["commit"], r"^[0-9a-f]{40}$")
        self.assertFalse((target / update_name / "metadata.json").exists())
        self.assertFalse((target / update_name / "__pypackages__").exists())

        local_copy = custom / "SKILL.md"
        local_copy.write_bytes((backup / "SKILL.md").read_bytes())
        self.assertEqual(self.installed()[custom_name]["status"], "modified")
        for entry in (source / "skills").glob("*/SKILL.md"):
            entry.write_text(entry.read_text(encoding="utf-8").replace("initial content", "upstream update"),
                             encoding="utf-8")
        commit("upstream edits both skills")
        self.assertIn(f"{custom_name} has local changes", self.cli("check", status=1))
        self.cli("update", "--project", update_name)
        self.assertIn("upstream update", (target / update_name / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(local_copy.read_bytes(), (backup / "SKILL.md").read_bytes())
        self.assertEqual(self.installed()[custom_name]["status"], "modified")
        self.assertEqual(self.installed()[update_name]["status"], "tracked")
        self.assertEqual(self.lock()[custom_name], original_lock[custom_name])
        self.assertNotEqual(self.lock()[update_name]["commit"], original_lock[update_name]["commit"])
