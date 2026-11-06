from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1] / "skills/aitasks-maintenance"
QUERY = SKILL / "scripts/query_aitasks.py"
MAINTENANCE = SKILL / "scripts/maintain_aitasks.py"


class StandaloneQueryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="standalone query ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.records = self.project / ".aitasks"
        self.records.mkdir(parents=True)
        self.script = self.root / "single skill/scripts/query_aitasks.py"
        self.script.parent.mkdir(parents=True)
        shutil.copy2(QUERY, self.script)

    def run_query(self, *arguments, script=None):
        return subprocess.run(
            [sys.executable, "-B", str(script or self.script), "--project-root", str(self.project), *arguments],
            text=True, capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def result(self, *arguments, script=None):
        result = self.run_query(*arguments, script=script)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mode & 0o777)
                for path in self.root.rglob("*") if path.is_file()}

    def mixed_lessons(self):
        return (
            "# Lessons\n\n## Legacy refund\nPreserve zero retries in refund exports.\n\n"
            "<!-- aitasks:lesson id=old created_at=2026-11-06 status=superseded superseded_by=current -->\n"
            "## Old refund retries\nOBSOLETE_SENTINEL: replace zero retries with three.\n\n"
            "<!-- aitasks:lesson id=current created_at=2026-11-06 last_used_at=- use_count=0 pinned=false -->\n"
            "## Current refund retries\n- 适用范围：refund exports\nPreserve zero retries.\n\n"
            "```markdown\n<!-- aitasks:lesson id=fake status=retired -->\n## Fenced example\n"
            "FENCED_EXAMPLE\n```\n\n### Details\nCURRENT_END\n\n"
            "<!-- aitasks:lesson id=next created_at=2026-11-06 last_used_at=- use_count=0 pinned=false -->\n"
            "## Unrelated record\nNEXT_RECORD_SENTINEL\n"
        )

    def test_single_file_query_handles_mixed_records_without_writes(self):
        (self.records / "lessons.md").write_text(self.mixed_lessons())
        before = self.snapshot()
        context = self.result("context", "--query", "refund retries", "--max-chars", "5000")
        self.assertEqual(context, self.result("context", "--query", "refund retries", "--max-chars", "5000",
                                              script=MAINTENANCE))
        identities = {row["id"] for row in context["lessons"]}
        self.assertIn("current", identities)
        self.assertNotIn("old", identities)
        self.assertNotIn("fake", identities)
        self.assertNotIn("OBSOLETE_SENTINEL", json.dumps(context))
        legacy = next(row for row in context["lessons"] if row["title"] == "Legacy refund")
        legacy_detail = self.result("get-record", "--kind", "lesson", "--id", legacy["id"])
        self.assertIn("Preserve zero retries", legacy_detail["content"])
        self.assertNotIn("aitasks:lesson", legacy_detail["content"])
        detail = self.result("get-record", "--kind", "lesson", "--id", "current", "--max-chars", "5000")
        self.assertIn("FENCED_EXAMPLE", detail["content"])
        self.assertIn("CURRENT_END", detail["content"])
        self.assertNotIn("NEXT_RECORD_SENTINEL", detail["content"])
        self.assertNotIn("OBSOLETE_SENTINEL", detail["content"])
        old = self.result("get-record", "--kind", "lesson", "--id", "old")
        self.assertEqual((old["status"], old["superseded_by"]), ("superseded", "current"))
        self.assertEqual(self.snapshot(), before)

    def test_builtin_and_project_aliases_work_without_sibling_assets(self):
        (self.records / "lessons.md").write_text("## Timeout handling\nKeep the timeout.\n")
        self.assertEqual(len(self.result("context", "--query", "超时")["lessons"]), 1)
        self.assertEqual(self.result("context", "--query", "deadline")["lessons"], [])
        (self.records / "search-aliases.json").write_text(json.dumps([["deadline", "timeout"]]))
        before = self.snapshot()
        self.assertEqual(len(self.result("context", "--query", "deadline")["lessons"]), 1)
        self.assertEqual(self.snapshot(), before)

    def test_builtin_alias_fallback_matches_the_distributed_alias_groups(self):
        groups = json.loads((SKILL / "assets/search-aliases.json").read_text())
        for group in groups:
            with self.subTest(group=group):
                (self.records / "lessons.md").write_text(f"## Recovery guidance\nPreserve {group[0]}.\n")
                before = self.snapshot()
                standalone = self.result("context", "--query", group[-1])
                self.assertEqual(len(standalone["lessons"]), 1)
                self.assertEqual(standalone, self.result("context", "--query", group[-1], script=MAINTENANCE))
                self.assertEqual(self.snapshot(), before)

    def test_archived_record_budget_and_stamp_match_existing_cli(self):
        archive = self.records / "archive/lessons-2026-11-01.md"
        archive.parent.mkdir()
        archive.write_text("<!-- aitasks:lesson id=archived created_at=2026-11-01 -->\n"
                           "## Refund archive\n" + "refund context " * 300)
        before = self.snapshot()
        context = self.result("context", "--query", "refund")
        self.assertTrue(context["searched_archive"])
        self.assertTrue(context["lessons"][0]["archived"])
        self.assertTrue(self.result("context", "--query", "refund", "--since", context["stamp"])["unchanged"])
        raw = self.run_query("get-record", "--kind", "lesson", "--id", "archived", "--max-chars", "900")
        self.assertEqual(raw.returncode, 0, raw.stderr)
        self.assertLessEqual(len(raw.stdout), 900)
        self.assertTrue(json.loads(raw.stdout)["truncated"])
        self.assertEqual(self.snapshot(), before)

    def test_todo_query_is_shared_and_no_write_commands_are_exposed(self):
        (self.records / "todo.md").write_text(
            "<!-- aitasks:todo id=task created_at=2026-11-06 status=active completed_at=- -->\n"
            "## Refund task\nPreserve retries.\n"
        )
        before = self.snapshot()
        self.assertEqual(self.result("list-todos", "--json"),
                         self.result("list-todos", "--json", script=MAINTENANCE))
        self.assertIn("Preserve retries", self.result("get-record", "--kind", "todo", "--id", "task")["content"])
        self.assertNotEqual(self.run_query("add-todo", "--title", "Unexpected").returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_missing_records_query_creates_no_directory_or_cache(self):
        self.records.rmdir()
        before = self.snapshot()
        self.assertEqual(self.result("context", "--query", "refund")["lessons"], [])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.records.exists())


if __name__ == "__main__":
    unittest.main()
