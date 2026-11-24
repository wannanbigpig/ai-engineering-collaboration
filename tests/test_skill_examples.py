from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/aitasks-maintenance"


class SkillCommandExampleTest(unittest.TestCase):
    def test_short_query_reference_runs_readonly_with_space_containing_paths(self):
        text = (SKILL / "references/query.md").read_text()
        commands = [line.replace('命中ID', 'known') for line in text.splitlines() if line.startswith('python3 ')]
        with tempfile.TemporaryDirectory(prefix="query examples ") as directory:
            root = Path(directory)
            copied = root / "skill copy"
            shutil.copytree(SKILL, copied)
            project = root / "project copy"
            records = project / '.aitasks'
            records.mkdir(parents=True)
            lesson = records / 'lessons.md'
            lesson.write_text('<!-- aitasks:lesson id=known created_at=2026-11-05 last_used_at=- use_count=0 pinned=false -->\n## 模块符号\n\n保留错误码。\n')
            before = {str(p.relative_to(project)):p.read_bytes() for p in project.rglob('*') if p.is_file()}
            env = dict(os.environ, AITASKS_TOOL=str(copied/'scripts/maintain_aitasks.py'), AITASKS_PROJECT=str(project))
            for command in commands:
                result = subprocess.run(['bash','-c',command],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsInstance(json.loads(result.stdout), dict)
            self.assertEqual(before, {str(p.relative_to(project)):p.read_bytes() for p in project.rglob('*') if p.is_file()})

    def test_no_python_examples_skip_fenced_record_files(self):
        shell = shutil.which('sh')
        if not shell or not shutil.which('rg'):
            self.skipTest('No sh or rg for the no-Python command example')
        sources = [SKILL / 'references/query.md', *(ROOT / 'skills' / name / 'SKILL.md' for name in (
            'ai-engineering-collaboration', 'change-impact-analysis', 'code-review', 'systematic-debugging'))]
        examples = []
        for source in sources:
            match = re.search(r'^ {0,3}```bash\n( *if rg .*?)^ {0,3}```$',
                              source.read_text(encoding='utf-8'), re.MULTILINE | re.DOTALL)
            self.assertIsNotNone(match, source)
            examples.append(dedent(match[1]))
        self.assertEqual(len(set(examples)), 1)
        command = examples[0].replace('关键词一|关键词二', 'retry')
        with tempfile.TemporaryDirectory() as directory:
            records = Path(directory) / '.aitasks'
            records.mkdir()
            lessons = records / 'lessons.md'
            plain = '<!-- aitasks:lesson id=real status=active -->\n## retry title\n\nBody.\n'
            lessons.write_text(plain, encoding='utf-8')
            visible = subprocess.run([shell, '-c', command], cwd=directory, capture_output=True, text=True, check=True)
            self.assertEqual(visible.stdout.splitlines(), ['2:## retry title'])
            for fence in ('```', '~~~'):
                with self.subTest(fence=fence):
                    content = (plain + f'\n{fence}md\n<!-- aitasks:lesson id=example status=active -->\n'
                               f'## retry example in body\n{fence}\n')
                    lessons.write_text(content, encoding='utf-8')
                    skipped = subprocess.run([shell, '-c', command], cwd=directory, capture_output=True, text=True, check=True)
                    self.assertEqual(skipped.stdout, '')
                    self.assertIn('未验证', skipped.stderr)
                    self.assertEqual(lessons.read_text(encoding='utf-8'), content)

    def test_documented_read_only_commands_work_with_space_containing_paths(self) -> None:
        text = (SKILL / "references/maintenance.md").read_text(encoding="utf-8")
        block = text.split("```bash\n", 1)[1].split("```", 1)[0]
        # Execute only the documented read-only operations in a temporary project.
        commands = [
            line for line in block.splitlines()
            if line.startswith("python3 ")
            and any(f" {name} " in line for name in ("context", "get-record", "list-todos"))
        ]
        self.assertEqual(len(commands), 3)
        shells = [name for name in ("bash", "zsh") if shutil.which(name)]
        if not shells:
            self.skipTest("Neither bash nor zsh is available")
        with tempfile.TemporaryDirectory(prefix="skill examples ") as directory:
            root = Path(directory)
            copied = root / "skill copy"
            shutil.copytree(SKILL, copied)
            project = root / "project with spaces"
            records = project / ".aitasks"
            records.mkdir(parents=True)
            (records / "lessons.md").write_text('<!-- aitasks:lesson id=known created_at=2026-11-05 last_used_at=- use_count=0 pinned=false -->\n## 模块符号\n\n保留错误码。\n')
            before = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
            environment = dict(os.environ)
            environment.update(
                AITASKS_TOOL=str(copied / "scripts/maintain_aitasks.py"),
                AITASKS_PROJECT=str(project),
                AITASKS_LESSON_ID="known",
                PATH=str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", ""),
                PYTHONDONTWRITEBYTECODE="1",
            )
            for shell in shells:
                for command in commands:
                    with self.subTest(shell=shell, command=command):
                        result = subprocess.run(
                            [shell, "-f", "-c", command], env=environment,
                            text=True, capture_output=True, check=False,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIsInstance(json.loads(result.stdout), dict)
                        self.assertEqual(before, {str(p.relative_to(project)): p.read_bytes()
                                                  for p in project.rglob("*") if p.is_file()})

    def test_documented_write_workflow_uses_returned_ids_and_task_deduplication(self) -> None:
        text = (SKILL / "references/maintenance.md").read_text(encoding="utf-8")
        block = text.split("```bash\n", 1)[1].split("```", 1)[0]
        commands = [line for line in block.splitlines()
                    if line.startswith("python3 ") and any(f" {name} " in line for name in
                        ("add-todo", "upsert-lesson", "mark-used", "finish-todo"))]
        self.assertEqual(len(commands), 4)
        shells = [name for name in ("bash", "zsh") if shutil.which(name)]
        if not shells:
            self.skipTest("Neither bash nor zsh is available")
        with tempfile.TemporaryDirectory(prefix="skill examples ") as directory:
            root = Path(directory)
            copied = root / "skill copy"
            shutil.copytree(SKILL, copied)
            for shell in shells:
                project = root / (shell + " project with spaces")
                (project / ".aitasks").mkdir(parents=True)
                environment = dict(os.environ)
                environment.update(
                    AITASKS_TOOL=str(copied / "scripts/maintain_aitasks.py"),
                    AITASKS_PROJECT=str(project),
                    PATH=str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", ""),
                    PYTHONDONTWRITEBYTECODE="1",
                )
                for command in commands:
                    with self.subTest(shell=shell, command=command):
                        result = subprocess.run(
                            [shell, "-f", "-c", command], env=environment,
                            text=True, capture_output=True, check=False,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        data = json.loads(result.stdout)
                        if " add-todo " in command:
                            environment["AITASKS_TASK_ID"] = data["id"]
                        elif " upsert-lesson " in command:
                            environment["AITASKS_LESSON_ID"] = data["id"]
                        elif " mark-used " in command:
                            repeated = subprocess.run([shell, "-f", "-c", command], env=environment,
                                                      text=True, capture_output=True, check=False)
                            self.assertEqual(repeated.returncode, 0, repeated.stderr)
                            self.assertFalse(json.loads(repeated.stdout)["changed"])
                            self.assertEqual(json.loads(repeated.stdout)["use_count"], 1)
                        elif " finish-todo " in command:
                            self.assertEqual(data["id"], environment["AITASKS_TASK_ID"])
                            self.assertEqual(data["status"], "completed")
                self.assertIn("## 任务标题", (project / ".aitasks/todo.md").read_text())
                self.assertIn("## 经验标题", (project / ".aitasks/lessons.md").read_text())
                self.assertIn("实际结果", (project / ".aitasks/todo.md").read_text())
                self.assertIn("use_count=1", (project / ".aitasks/lessons.md").read_text())


if __name__ == "__main__":
    unittest.main()
