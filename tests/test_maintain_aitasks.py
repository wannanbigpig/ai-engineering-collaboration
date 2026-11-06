from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills/aitasks-maintenance/scripts/maintain_aitasks.py"
)
MARKER = (
    "<!-- aitasks:lesson created_at=2026-09-15 "
    "last_used_at=- use_count=0 pinned=false -->\n"
)
SPEC = importlib.util.spec_from_file_location("maintain_aitasks", SCRIPT)
maintenance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = maintenance
SPEC.loader.exec_module(maintenance)


class MaintainAitasksTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.aitasks = self.root / ".aitasks"
        self.aitasks.mkdir()
        self.lessons = self.aitasks / "lessons.md"

    def run_script(
        self, *arguments: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--project-root",
                str(self.root),
                "--today",
                "2026-09-15",
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def find(self, query: str, *arguments: str) -> str:
        result = self.run_script("find-lessons", "--query", query, *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_json_writes_chain_ids_and_report_idempotent_results(self) -> None:
        created = self.run_script("add-todo", "--title", "JSON task", "--goal", "Keep offset",
                                  "--verify", "Run regression", "--maintain", "--json")
        self.assertEqual(created.returncode, 0, created.stderr)
        task = json.loads(created.stdout)
        self.assertEqual((task["kind"], task["action"], task["status"]), ("todo", "created", "active"))
        self.assertTrue(task["changed"])
        self.assertTrue(task["maintenance_checked"])
        lesson_result = self.run_script("upsert-lesson", "--explicit", "--title", "Offset",
            "--context", "Export", "--problem", "Lost offset", "--cause", "Conversion",
            "--resolution", "Keep original offset", "--scope", "Export")
        self.assertEqual(lesson_result.returncode, 0, lesson_result.stderr)
        lesson = json.loads(lesson_result.stdout)
        used_args = ("mark-used", "--id", lesson["id"], "--task-id", task["id"], "--maintain", "--json")
        used = self.run_script(*used_args)
        self.assertEqual(used.returncode, 0, used.stderr)
        counted = json.loads(used.stdout)
        self.assertEqual(counted["id"], lesson["id"])
        self.assertEqual(counted["use_count"], 1)
        self.assertTrue(counted["changed"])
        self.assertTrue(counted["maintenance_checked"])
        before = self.lessons.read_bytes()
        repeated = self.run_script(*used_args)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        noop = json.loads(repeated.stdout)
        self.assertEqual(noop["action"], "unchanged")
        self.assertFalse(noop["changed"])
        self.assertFalse(noop["maintenance_checked"])
        self.assertEqual(noop["use_count"], 1)
        self.assertEqual(self.lessons.read_bytes(), before)
        finish_args = ("finish-todo", "--id", task["id"], "--result", "Fixed", "--verify", "Passed", "--json")
        finished = self.run_script(*finish_args)
        self.assertEqual(finished.returncode, 0, finished.stderr)
        done = json.loads(finished.stdout)
        self.assertEqual((done["id"], done["status"]), (task["id"], "completed"))
        self.assertTrue(done["changed"])
        completed = (self.aitasks / "todo.md").read_bytes()
        repeated = self.run_script(*finish_args)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertFalse(json.loads(repeated.stdout)["changed"])
        self.assertTrue(json.loads(repeated.stdout)["maintenance_checked"])
        self.assertEqual((self.aitasks / "todo.md").read_bytes(), completed)

    def test_json_completion_keeps_stdout_parseable_when_archiving(self) -> None:
        path = self.aitasks / "todo.md"
        old = "<!-- aitasks:todo id=old created_at=2026-09-01 status=completed completed_at=2026-09-10 -->\n## Old\nOld result.\n\n"
        path.write_text(old + "<!-- aitasks:todo id=current created_at=2026-09-15 status=active completed_at=- -->\n## Current\n")
        result = self.run_script("finish-todo", "--id", "current", "--result", "Done", "--todo-count-trigger", "2", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["maintenance_checked"])
        self.assertTrue(data["changed"])
        self.assertNotIn("## Old", path.read_text())
        self.assertIn(old.strip(), next((self.aitasks / "archive").glob("todo-*.md")).read_text())

    def test_json_write_failure_has_no_success_payload(self) -> None:
        result = self.run_script("finish-todo", "--id", "missing", "--result", "Done", "--json")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("selector", result.stderr)
        self.assertFalse((self.aitasks / "todo.md").exists())

    def test_legacy_write_commands_offer_json_without_requiring_maintenance(self) -> None:
        result = self.run_script("add-lesson", "--title", "Legacy", "--context", "Context",
            "--problem", "Problem", "--cause", "Cause", "--resolution", "Resolution", "--scope", "Scope", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual((data["kind"], data["status"]), ("lesson", "active"))
        self.assertFalse(data["maintenance_checked"])
        (self.aitasks / "todo.md").write_text("<!-- aitasks:todo id=old created_at=2026-09-15 status=active completed_at=- -->\n## Old\n")
        args = ("set-todo-status", "--todo", "Old", "--status", "cancelled", "--json")
        first = self.run_script(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(json.loads(first.stdout)["changed"])
        second = self.run_script(*args)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(json.loads(second.stdout)["changed"])

    def test_metadata_updates_preserve_existing_format_and_mode(self) -> None:
        for kind in ("todo", "lesson"):
            with self.subTest(kind=kind):
                path = self.aitasks / ("todo.md" if kind == "todo" else "lessons.md")
                fields = ("status=active completed_at=-" if kind == "todo" else
                          "last_used_at=- use_count=0 pinned=false")
                original = (
                    f"# Records\r\n\r\n  <!-- aitasks:{kind}   id=first created_at=2026-09-15 {fields} -->\r\n"
                    f"## First\r\n\r\nKeep this body.  \r\n\r\n"
                    f"<!-- aitasks:{kind}   id=second  created_at=2026-09-15 {fields} -->\r\n"
                    f"## Second\r\nUnchanged.\r\n"
                ).encode()
                path.write_bytes(original)
                path.chmod(0o640)
                if kind == "todo":
                    result = self.run_script("set-todo-status", "--todo", "First", "--status", "completed")
                    expected = original.replace(b"status=active completed_at=-",
                                                b"status=completed completed_at=2026-09-15", 1)
                else:
                    result = self.run_script("mark-used", "--lesson", "First")
                    expected = original.replace(b"last_used_at=- use_count=0",
                                                b"last_used_at=2026-09-15 use_count=1", 1)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(path.read_bytes(), expected)
                self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_finish_todo_updates_result_verification_and_status_by_id(self) -> None:
        created = self.run_script("add-todo", "--title", "Task", "--goal", "Fix behavior",
                                  "--verify", "Planned check", "--maintain")
        self.assertEqual(created.returncode, 0, created.stderr)
        listed = self.run_script("list-todos", "--json")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        task = json.loads(listed.stdout)["todos"][0]
        result = self.run_script("finish-todo", "--id", task["id"], "--result", "Fixed and checked",
                                 "--verify", "Regression passed")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (self.aitasks / "todo.md").read_text()
        self.assertIn("status=completed completed_at=2026-09-15", text)
        self.assertIn("Fixed and checked", text)
        self.assertIn("Regression passed", text)
        self.assertNotIn("待完成", text)
        self.assertEqual(json.loads(self.run_script("list-todos", "--json").stdout)["todos"], [])
        self.assertIn("Maintenance not due", result.stdout)

    def test_finish_todo_checks_threshold_and_archives_old_record(self) -> None:
        path = self.aitasks / "todo.md"
        old = "<!-- aitasks:todo id=old created_at=2026-09-01 status=completed completed_at=2026-09-10 -->\n## Old\nKeep old result.\n\n"
        current = "<!-- aitasks:todo id=current created_at=2026-09-15 status=active completed_at=- -->\n## Current\n\n### 结果\n\n待完成。\n"
        path.write_text(old + current)
        result = self.run_script("finish-todo", "--id", "current", "--result", "Done",
                                 "--todo-count-trigger", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("## Old", path.read_text())
        self.assertIn("Done", path.read_text())
        archive = next((self.aitasks / "archive").glob("todo-*.md"))
        self.assertIn(old.strip(), archive.read_text())

    def test_finish_todo_preflight_failure_preserves_result_and_state(self) -> None:
        path = self.aitasks / "todo.md"
        original = ("<!-- aitasks:todo id=duplicate created_at=2026-09-15 status=active completed_at=- -->\n"
                    "## First\n\n### 结果\n\n待完成。\n\n"
                    "<!-- aitasks:todo id=duplicate created_at=2026-09-15 status=active completed_at=- -->\n"
                    "## Other\nUnchanged.\n")
        path.write_text(original)
        result = self.run_script("finish-todo", "--todo", "First", "--result", "Done")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ID collision", result.stderr)
        self.assertEqual(path.read_text(), original)
        self.assertFalse((self.aitasks / ".maintenance.json").exists())

    def test_finish_todo_id_disambiguates_titles_and_readonly_list_has_no_writes(self) -> None:
        path = self.aitasks / "todo.md"
        first = "<!-- aitasks:todo id=first created_at=2026-09-15 status=active completed_at=- -->\n## Same\nOriginal first.\n\n"
        second = first.replace("id=first", "id=second").replace("Original first", "Original second")
        path.write_text(first + second)
        before = {p.name: p.read_bytes() for p in self.aitasks.iterdir()}
        listed = self.run_script("list-todos", "--json")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(len(json.loads(listed.stdout)["todos"]), 2)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.aitasks.iterdir()})
        done = self.run_script("finish-todo", "--id", "second", "--result", "Cancelled",
                               "--status", "cancelled")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(path.read_text().startswith(first))
        self.assertIn("status=cancelled", path.read_text())

    def test_cleanup_preserves_crlf_records_and_recovers_archived_content(self) -> None:
        old = (MARKER.replace("2026-09-15", "2020-01-01") + "## Old\nbody\n\n").replace("\n", "\r\n")
        keep = "## Legacy\r\nKeep this text.  \r\n"
        self.lessons.write_bytes((old + keep).encode())
        self.lessons.chmod(0o640)
        first = self.run_script("cleanup", "--force", "--apply")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.lessons.read_bytes(), keep.encode())
        self.assertEqual(self.lessons.stat().st_mode & 0o777, 0o640)
        archive = next((self.aitasks / "archive").glob("lessons-*.md"))
        archived = archive.read_bytes()
        self.lessons.write_bytes((old + keep).encode())
        second = self.run_script("cleanup", "--force", "--apply")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(archive.read_bytes(), archived)
        self.assertEqual(self.lessons.read_bytes(), keep.encode())

    def test_json_returns_complete_records_with_owned_metadata_and_source_lines(self) -> None:
        original = (
            "# 经验\n\n## 日期旧经验\n保留 timezone offset。\n"
            "### 条件\n仅按外部契约转换。\n\n"
            + MARKER.replace("use_count=0", "use_count=3")
            + "## 日期新经验\n带记录的条件。\n\n"
            + MARKER + "## 其他经验\n无关正文。\n"
        )
        self.lessons.write_text(original, encoding="utf-8")
        result = json.loads(self.find("日期", "--json"))
        legacy, tracked = result["matches"]
        self.assertEqual(legacy["title"], "日期旧经验")
        self.assertIsNone(legacy["metadata"])
        self.assertIsNone(legacy["use_count"])
        self.assertEqual(legacy["use_count_status"], "missing")
        self.assertIn("### 条件", legacy["content"])
        self.assertNotIn("aitasks:", legacy["content"])
        self.assertEqual(tracked["metadata"]["use_count"], "3")
        self.assertEqual(tracked["use_count"], 3)
        self.assertEqual(tracked["use_count_status"], "recorded")
        self.assertNotIn("其他经验", tracked["content"])
        self.assertNotIn("aitasks:", tracked["content"])
        for record in (legacy, tracked):
            source = record["source"]
            self.assertEqual(Path(source["path"]), self.lessons.resolve())
            lines = original.splitlines()
            self.assertEqual(lines[source["title_line"] - 1], "## " + record["title"])
            selected = "\n".join(lines[source["start_line"] - 1:source["end_line"]])
            self.assertIn(record["content"], selected)
            self.assertNotIn("## 其他经验", selected)
        self.assertEqual(legacy["source"], {"path": str(self.lessons.resolve()), "start_line": 3, "end_line": 6, "title_line": 3})
        self.assertEqual(tracked["source"]["start_line"], 8)
        self.assertEqual(tracked["source"]["end_line"], 10)
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), original)
        self.assertEqual(list(self.aitasks.iterdir()), [self.lessons])

    def test_json_distinguishes_zero_missing_and_invalid_count(self) -> None:
        for raw, expected, status in [("0", 0, "recorded"), ("3", 3, "recorded"),
                                      ("-1", None, "invalid"), ("oops", None, "invalid")]:
            with self.subTest(raw=raw):
                self.lessons.write_text(MARKER.replace("use_count=0", "use_count=" + raw) + "## 日期\n条件\n")
                record = json.loads(self.find("日期", "--json"))["matches"][0]
                self.assertEqual(record["use_count"], expected)
                self.assertEqual(record["use_count_status"], status)
                self.assertEqual(record["metadata"]["use_count"], raw)
        self.lessons.write_text(MARKER.replace(" use_count=0", "") + "## 日期\n条件\n")
        record = json.loads(self.find("日期", "--json"))["matches"][0]
        self.assertIsNone(record["use_count"])
        self.assertEqual(record["use_count_status"], "missing")

    def test_json_no_match_limit_and_literal_query(self) -> None:
        empty = json.loads(self.find("不存在", "--json"))
        self.assertEqual(empty["matches"], [])
        self.lessons.write_text("## 日期一\n内容\n## 日期二\n内容\n")
        self.assertEqual(len(json.loads(self.find("日期", "--json", "--limit", "1"))["matches"]), 1)
        self.assertEqual(json.loads(self.find("日期|内容", "--json"))["matches"], [])
        result = self.run_script("find-lessons", "--query", "日期", "--json", "--include-content")
        self.assertNotEqual(result.returncode, 0)

    def test_finds_legacy_body_without_writing_or_creating_metadata(self) -> None:
        original = "# Lessons\n\n## 旧经验\n\n使用 UTF-8 读取中文。\n"
        self.lessons.write_text(original, encoding="utf-8")

        result = self.find("utf-8")

        self.assertEqual(
            result,
            "- 旧经验 (created_at=-, last_used_at=-, use_count=-, pinned=-)\n",
        )
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), original)
        self.assertEqual(list(self.aitasks.iterdir()), [self.lessons])

    def test_mixed_records_keep_source_order_and_do_not_duplicate_subheadings(self) -> None:
        self.lessons.write_text(
            "# Lessons\n\n## Legacy first\nkeyword first\n"
            "### Details\nkeyword nested\n\n"
            + MARKER
            + "## Tracked\nkeyword modern\n### Evidence\nkeyword proof\n\n"
            "## Legacy last\nkeyword last\n",
            encoding="utf-8",
        )

        lines = self.find("keyword").splitlines()

        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("- Legacy first ("))
        self.assertTrue(lines[1].startswith("- Tracked (created_at=2026-09-15,"))
        self.assertTrue(lines[2].startswith("- Legacy last ("))
        limited = self.find("keyword", "--limit", "2").splitlines()
        self.assertEqual(limited[:2], lines[:2])
        self.assertIn("2 of 3", limited[-1])

    def test_search_ranks_titles_and_pinned_matches_and_reports_truncation(self) -> None:
        self.lessons.write_text(
            MARKER + "## Body match\nrefund details\n\n"
            + MARKER.replace("pinned=false", "pinned=true") + "## Pinned body\nrefund\n\n"
            + MARKER + "## refund\nexact title\n", encoding="utf-8")
        response = json.loads(self.find("refund", "--json", "--limit", "2"))
        self.assertEqual([r["title"] for r in response["matches"]], ["refund", "Pinned body"])
        self.assertEqual(response["total_matches"], 3)
        self.assertTrue(response["truncated"])
        self.assertFalse(response["searched_archive"])
        invalid = self.run_script("find-lessons", "--query", "refund", "--limit", "0")
        self.assertNotEqual(invalid.returncode, 0)

    def test_search_falls_back_to_archive_and_preserves_source_without_writes(self) -> None:
        self.lessons.write_text("## Active\nunrelated\n")
        archive = self.aitasks / "archive" / "lessons-2026-09-01.md"
        archive.parent.mkdir()
        archive.write_text(MARKER + "## Archived refund\nrefund rule\n")
        before = {str(p): p.read_bytes() for p in self.aitasks.rglob("*") if p.is_file()}
        response = json.loads(self.find("refund", "--json"))
        self.assertEqual(len(response["matches"]), 1)
        self.assertEqual(response["matches"][0]["source"]["path"], str(archive.resolve()))
        self.assertTrue(response["searched_archive"])
        self.assertIn("archive:", self.find("refund"))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.aitasks.rglob("*") if p.is_file()})

    def test_archive_is_only_searched_on_miss_or_when_explicitly_included(self) -> None:
        self.lessons.write_text(MARKER + "## Active\nrefund rule\n")
        archive = self.aitasks / "archive" / "lessons-2026-09-01.md"
        archive.parent.mkdir()
        archive.write_text(MARKER + "## Archived\nrefund rule\n")
        response = json.loads(self.find("refund", "--json"))
        self.assertEqual(response["total_matches"], 1)
        self.assertFalse(response["searched_archive"])
        response = json.loads(self.find("refund", "--json", "--include-archive"))
        self.assertEqual(response["total_matches"], 2)
        self.assertTrue(response["searched_archive"])

    def test_legacy_content_stops_before_metadata_and_preserves_nested_details(self) -> None:
        legacy = "## Legacy\nkeyword\n### Details\nnested content\n\n"
        self.lessons.write_text(
            "# Lessons\n\n" + legacy + MARKER + "## Tracked\nmodern body\n",
            encoding="utf-8",
        )

        result = self.find("keyword", "--include-content")

        self.assertEqual(result, legacy.rstrip() + "\n")
        self.assertNotIn("aitasks:", result)
        self.assertNotIn("Legacy", self.find("created_at"))

    def test_fenced_headings_do_not_split_legacy_records(self) -> None:
        legacy = (
            "## Legacy\nkeyword\n\n```markdown\n"
            "## keyword code example\n```\n\n"
            "~~~markdown\n# keyword other example\n~~~\n"
        )
        self.lessons.write_text(
            "# Lessons\n\n" + legacy + "\n## Another\nother\n",
            encoding="utf-8",
        )

        self.assertEqual(len(self.find("keyword").splitlines()), 1)
        self.assertEqual(self.find("keyword", "--include-content"), legacy.rstrip() + "\n")

    def test_legacy_search_preserves_fenced_metadata_examples(self) -> None:
        for fence in ("```", "~~~"):
            with self.subTest(fence=fence):
                legacy = ("## Legacy\nkeyword\n" + fence + "md\n" + MARKER
                          + "## Example\n" + fence + "\nTail\n")
                original = "# Lessons\n\n" + legacy + MARKER + "## Tracked\nother\n"
                self.lessons.write_text(original, encoding="utf-8")
                self.assertEqual(self.find("keyword", "--include-content"), legacy)
                result = json.loads(self.find("keyword", "--json"))["matches"]
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["content"], legacy.rstrip())
                self.assertIsNone(result[0]["metadata"])
                self.assertEqual(self.lessons.read_text(encoding="utf-8"), original)

    def test_multiple_top_level_records_and_deeper_records_are_searchable(self) -> None:
        for contents, expected in (
            ("# First\nkeyword\n# Second\nkeyword\n", ["First", "Second"]),
            (
                "# Lessons\n### First\nkeyword\n#### Details\nkeyword\n"
                "### Second\nkeyword\n",
                ["First", "Second"],
            ),
        ):
            with self.subTest(contents=contents):
                self.lessons.write_text(contents, encoding="utf-8")
                titles = [
                    line.split(" (")[0][2:]
                    for line in self.find("keyword").splitlines()
                ]
                self.assertEqual(titles, expected)

    def test_document_title_is_not_returned_as_legacy_record_in_tracked_file(self) -> None:
        self.lessons.write_text(
            "# Lessons\n\n" + MARKER + "## Tracked\nmodern\n",
            encoding="utf-8",
        )

        self.assertEqual(self.find("Lessons"), "No lessons matched.\n")
        self.assertEqual(
            self.find("modern", "--include-content"),
            MARKER + "## Tracked\nmodern\n",
        )

    def test_legacy_search_does_not_make_legacy_records_mutable_or_archivable(self) -> None:
        original = "## Legacy\nkeyword\n"
        self.lessons.write_text(original, encoding="utf-8")
        self.assertIn("Legacy", self.find("keyword"))

        mark = self.run_script("mark-used", "--lesson", "Legacy")
        cleanup = self.run_script("cleanup", "--force", "--apply")

        self.assertNotEqual(mark.returncode, 0)
        self.assertIn("missing metadata", mark.stderr)
        self.assertEqual(cleanup.returncode, 0, cleanup.stderr)
        self.assertIn("Tracked records: 0 lessons", cleanup.stdout)
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), original)
        self.assertFalse((self.aitasks / "archive").exists())

    def test_cleanup_of_mixed_file_archives_only_tracked_expired_record(self) -> None:
        before = "# Lessons\n\n## Legacy first\nkeyword first\n\n"
        after = "## Legacy last\nkeyword last\n"
        tracked = MARKER.replace("2026-09-15", "2020-01-01") + "## Old tracked\nbody\n\n"
        self.lessons.write_text(before + tracked + after, encoding="utf-8")
        self.assertEqual(len(self.find("keyword").splitlines()), 2)

        result = self.run_script("cleanup", "--force", "--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), before + after)
        archives = list((self.aitasks / "archive").glob("*.md"))
        self.assertEqual(len(archives), 1)
        archived = archives[0].read_text(encoding="utf-8")
        self.assertIn("## Old tracked", archived)
        self.assertNotIn("Legacy", archived)

    def test_cleanup_ignores_example_marker_inside_fenced_lesson(self) -> None:
        original = (
            MARKER + "## Real lesson\nMetadata example:\n\n```md\n"
            + MARKER.replace("2026-09-15", "2020-01-01")
            + "## Example marker\n```\nEssential tail.\n\n"
            + "    " + MARKER.replace("2026-09-15", "2020-01-01")
            + "    ## Indented example\n"
        )
        self.lessons.write_text(original, encoding="utf-8")

        result = self.run_script("cleanup", "--force", "--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Tracked records: 1 lessons", result.stdout)
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), original)
        self.assertFalse((self.aitasks / "archive").exists())

    def test_cleanup_without_expired_records_updates_check_state_without_archive(self) -> None:
        original = MARKER + "## Recent\nbody\n"
        self.lessons.write_text(original, encoding="utf-8")
        state_path = self.aitasks / ".maintenance.json"
        state_path.write_text('{"last_cleanup_at": "2026-01-01"}\n', encoding="utf-8")

        preview = self.run_script("cleanup")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("Eligible for archive: 0 lessons, 0 todos", preview.stdout)
        self.assertEqual(
            json.loads(state_path.read_text())["last_cleanup_at"], "2026-01-01"
        )

        applied = self.run_script("cleanup", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(
            json.loads(state_path.read_text()), {"last_cleanup_at": "2026-09-15"}
        )
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), original)
        self.assertFalse((self.aitasks / "archive").exists())
        self.assertFalse((self.aitasks / "todo.md").exists())

        status = self.run_script("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("Maintenance not due.", status.stdout)

    def test_count_trigger_archives_recent_completed_todos_before_age_limit(self) -> None:
        todo_path = self.aitasks / "todo.md"
        todo_path.write_text(
            "<!-- aitasks:todo created_at=2026-09-01 status=completed completed_at=2026-09-10 -->\n"
            "## Old completed\nbody\n\n"
            "<!-- aitasks:todo created_at=2026-09-02 status=completed completed_at=2026-09-11 -->\n"
            "## New completed\nbody\n\n"
            "<!-- aitasks:todo created_at=2026-09-03 status=active completed_at=- -->\n"
            "## Active\nbody\n",
            encoding="utf-8",
        )

        preview = self.run_script("cleanup", "--todo-count-trigger", "2")
        self.assertIn("Eligible for archive: 0 lessons, 1 todos", preview.stdout)
        self.assertIn("- todo: Old completed", preview.stdout)
        self.assertIn("Old completed", todo_path.read_text(encoding="utf-8"))

        applied = self.run_script("cleanup", "--todo-count-trigger", "2", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertNotIn("Old completed", todo_path.read_text(encoding="utf-8"))
        self.assertIn("New completed", todo_path.read_text(encoding="utf-8"))
        self.assertIn("Active", todo_path.read_text(encoding="utf-8"))
        archive = next((self.aitasks / "archive").glob("todo-*.md"))
        self.assertIn("Old completed", archive.read_text(encoding="utf-8"))

    def test_count_trigger_prefers_unused_lessons_and_preserves_pinned(self) -> None:
        self.lessons.write_text(
            "<!-- aitasks:lesson created_at=2026-09-01 last_used_at=- use_count=2 pinned=true -->\n"
            "## Pinned\nbody\n\n"
            "<!-- aitasks:lesson created_at=2026-09-02 last_used_at=2026-09-10 use_count=2 pinned=false -->\n"
            "## Used\nbody\n\n"
            "<!-- aitasks:lesson created_at=2026-09-03 last_used_at=- use_count=0 pinned=false -->\n"
            "## Unused\nbody\n",
            encoding="utf-8",
        )

        preview = self.run_script("cleanup", "--lesson-count-trigger", "3")
        self.assertIn("Eligible for archive: 1 lessons, 0 todos", preview.stdout)
        self.assertIn("- lesson: Unused", preview.stdout)
        applied = self.run_script("cleanup", "--lesson-count-trigger", "3", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        current = self.lessons.read_text(encoding="utf-8")
        self.assertIn("Pinned", current)
        self.assertIn("Used", current)
        self.assertNotIn("Unused", current)
        archive = next((self.aitasks / "archive").glob("lessons-*.md"))
        self.assertIn("Unused", archive.read_text(encoding="utf-8"))

    def test_cleanup_rejects_colliding_legacy_ids_without_removing_records(self) -> None:
        marker = MARKER.replace("2026-09-15", "2020-01-01")
        original = marker + "## Same title\nfirst body\n\n" + marker + "## Same title\nsecond body\n"
        self.lessons.write_text(original, encoding="utf-8")

        result = self.run_script("cleanup", "--force", "--apply")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ID collision", result.stderr)
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), original)
        self.assertFalse((self.aitasks / "archive").exists())
        self.assertFalse((self.aitasks / ".maintenance.json").exists())

    def test_cleanup_rejects_duplicate_id_even_when_only_one_record_is_selected(self) -> None:
        shared = "7bb2ce3b71d14856ac7affe064e4f04c"
        for kind in ("lesson", "todo"):
            with self.subTest(kind=kind):
                path = self.aitasks / ("lessons.md" if kind == "lesson" else "todo.md")
                if kind == "lesson":
                    old = f"<!-- aitasks:lesson id={shared} created_at=2020-01-01 last_used_at=- use_count=0 pinned=false -->\n"
                    recent = f"<!-- aitasks:lesson id={shared} created_at=2026-09-15 last_used_at=- use_count=0 pinned=false -->\n"
                else:
                    old = f"<!-- aitasks:todo id={shared} created_at=2020-01-01 status=completed completed_at=2020-01-02 -->\n"
                    recent = f"<!-- aitasks:todo id={shared} created_at=2026-09-15 status=active completed_at=- -->\n"
                original = old + "## Old\nold body\n\n" + recent + "## Recent\nrecent body\n"
                path.write_text(original, encoding="utf-8")

                result = self.run_script("cleanup", "--force", "--apply")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ID collision", result.stderr)
                self.assertEqual(path.read_text(encoding="utf-8"), original)
                self.assertFalse((self.aitasks / "archive").exists())
                self.assertFalse((self.aitasks / ".maintenance.json").exists())
                path.unlink()

    def test_add_records_preserve_existing_bytes_and_produce_template_metadata(self) -> None:
        todo = self.aitasks / "todo.md"
        todo.write_bytes(b"# Existing\r\n\r\n## Legacy\r\nbody without newline")
        todo.chmod(0o640)
        self.lessons.write_text("# Lessons\n\n## Old lesson\nold content\n", encoding="utf-8")
        todo_result = self.run_script(
            "add-todo", "--title", "修复日期", "--goal", "保留原始 offset", "--verify", "运行相关测试",
        )
        lesson_result = self.run_script(
            "add-lesson", "--title", "日期偏移", "--context", "导出", "--problem", "偏移丢失",
            "--cause", "未确认", "--resolution", "检查契约", "--scope", "日期序列化",
        )

        self.assertEqual(todo_result.returncode, 0, todo_result.stderr)
        self.assertEqual(lesson_result.returncode, 0, lesson_result.stderr)
        self.assertTrue(todo.read_bytes().startswith(b"# Existing\r\n\r\n## Legacy\r\nbody without newline"))
        self.assertEqual(todo.stat().st_mode & 0o777, 0o640)
        todo_records = maintenance.load_record_file(todo, "todo").records
        lesson_records = maintenance.load_record_file(self.lessons, "lesson").records
        self.assertEqual(len(todo_records), 1)
        self.assertEqual(len(lesson_records), 1)
        self.assertRegex(todo_records[0].fields["id"], r"^[0-9a-f]{32}$")
        self.assertRegex(lesson_records[0].fields["id"], r"^[0-9a-f]{32}$")
        self.assertNotEqual(todo_records[0].fields["id"], lesson_records[0].fields["id"])
        self.assertEqual(todo_records[0].fields["created_at"], "2026-09-15")
        self.assertEqual(todo_records[0].fields["status"], "active")
        self.assertEqual(todo_records[0].fields["completed_at"], "-")
        self.assertEqual(lesson_records[0].fields["use_count"], "0")
        self.assertEqual(lesson_records[0].fields["last_used_at"], "-")
        self.assertEqual(lesson_records[0].fields["pinned"], "false")
        self.assertIn("未确认", lesson_records[0].raw)

    def test_add_rejects_duplicate_titles_invalid_content_and_missing_directory(self) -> None:
        self.lessons.write_text("# Lessons\n\n## Legacy title\nold\n", encoding="utf-8")
        original = self.lessons.read_bytes()
        base = ("add-lesson", "--title", "Legacy title", "--context", "context", "--problem", "problem",
                "--cause", "未确认", "--resolution", "resolution", "--scope", "scope")
        duplicate = self.run_script(*base)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("title", duplicate.stderr)
        self.assertEqual(self.lessons.read_bytes(), original)

        todo = self.aitasks / "todo.md"
        invalid = self.run_script("add-todo", "--title", "坏\n标题", "--goal", "goal", "--verify", "verify")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse(todo.exists())
        invalid_body = self.run_script("add-todo", "--title", "bad body", "--goal", "text\n## Other record", "--verify", "verify")
        self.assertNotEqual(invalid_body.returncode, 0)
        self.assertFalse(todo.exists())

        self.lessons.unlink()
        for artifact in self.aitasks.iterdir():
            artifact.unlink()
        self.aitasks.rmdir()
        missing = self.run_script("add-todo", "--title", "Task", "--goal", "goal", "--verify", "verify")
        self.assertNotEqual(missing.returncode, 0)
        self.assertFalse(self.aitasks.exists())

    def test_concurrent_adds_are_serialized_and_duplicate_title_is_rejected(self) -> None:
        def add(title: str) -> subprocess.CompletedProcess[str]:
            return self.run_script("add-todo", "--title", title, "--goal", "goal", "--verify", "verify")

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(add, [f"Task {i}" for i in range(8)]))
        self.assertTrue(all(result.returncode == 0 for result in results),
                        "\n".join(result.stderr for result in results))
        records = maintenance.load_record_file(self.aitasks / "todo.md", "todo").records
        self.assertEqual({record.title for record in records}, {f"Task {i}" for i in range(8)})
        self.assertEqual(len({record.fields["id"] for record in records}), 8)

        with ThreadPoolExecutor(max_workers=2) as pool:
            duplicate_results = list(pool.map(add, ["Same task", "Same task"]))
        self.assertEqual(sorted(result.returncode == 0 for result in duplicate_results), [False, True])
        records = maintenance.load_record_file(self.aitasks / "todo.md", "todo").records
        self.assertEqual(sum(record.title == "Same task" for record in records), 1)

    def test_add_lesson_keeps_fenced_examples_inside_the_record(self) -> None:
        example = "```md\n" + MARKER + "## Example heading\n```"
        result = self.run_script(
            "add-lesson", "--title", "Use a metadata example", "--context", example,
            "--problem", "example problem", "--cause", "未确认", "--resolution", "check",
            "--scope", "scope", "--pinned",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        added = self.run_script(
            "add-lesson", "--title", "Next record", "--context", "another case",
            "--problem", "problem", "--cause", "未确认", "--resolution", "check", "--scope", "scope",
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        records = maintenance.load_record_file(self.lessons, "lesson").records
        self.assertEqual([record.title for record in records], ["Use a metadata example", "Next record"])
        self.assertEqual(records[0].fields["pinned"], "true")
        self.assertIn(example, records[0].raw)
        self.assertIn("## Example heading", self.find("metadata example", "--include-content"))

    def test_add_uses_distributed_template_once_without_replacing_user_text(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template change ") as directory:
            copied = Path(directory) / "skill"
            shutil.copytree(SCRIPT.parent.parent, copied)
            script = copied / "scripts/maintain_aitasks.py"
            template = copied / "assets/todo.md"
            template.write_text(template.read_text(encoding="utf-8").replace(
                "### 目标与范围", "### 自定义目标与范围"), encoding="utf-8")
            literal = "用户文本保留 {{计划的必要验证；完成后写入实际结果。}}"
            command = [sys.executable, "-B", str(script), "--project-root", str(self.root),
                       "--today", "2026-09-15", "add-todo", "--title", "Custom template",
                       "--goal", literal, "--verify", "实际验证"]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            contents = (self.aitasks / "todo.md").read_text(encoding="utf-8")
            self.assertIn("### 自定义目标与范围", contents)
            self.assertIn(literal, contents)
            self.assertIn("实际验证", contents)
            self.assertNotIn("<!-- 替换全部占位符", contents)

            template.unlink()
            result = subprocess.run(command[:8] + ["--title", "Missing template", "--goal", "goal", "--verify", "verify"],
                                    text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("template", result.stderr)
            self.assertEqual((self.aitasks / "todo.md").read_text(encoding="utf-8"), contents)

    def test_add_rejects_corrupt_template_before_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="template corrupt ") as directory:
            copied = Path(directory) / "skill"
            shutil.copytree(SCRIPT.parent.parent, copied)
            template = copied / "assets/lessons.md"
            original = template.read_text(encoding="utf-8")
            corruptions = (
                original.replace("pinned=false", "pinned=true"),
                original.replace("{{经验标题}}", "{{unknown}}"),
                original + "\n```md\nunclosed\n",
            )
            for corrupted in corruptions:
                with self.subTest(corrupted=corrupted[-35:]):
                    template.write_text(corrupted, encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, "-B", str(copied / "scripts/maintain_aitasks.py"), "--project-root", str(self.root),
                         "add-lesson", "--title", "Record", "--context", "context", "--problem", "problem",
                         "--cause", "未确认", "--resolution", "fix", "--scope", "scope"],
                        text=True, capture_output=True, check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("invalid lesson template", result.stderr)
                    self.assertFalse(self.lessons.exists())
                    self.assertEqual(list(self.aitasks.iterdir()), [])

    def test_add_rejects_open_fences_markers_and_symlink_targets(self) -> None:
        todo = self.aitasks / "todo.md"
        for goal in ("```md\nunclosed", "normal text\n" + MARKER):
            with self.subTest(goal=goal):
                result = self.run_script("add-todo", "--title", "Invalid", "--goal", goal, "--verify", "check")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(todo.exists())
        original = "# Existing\n\n```md\nunclosed example\n"
        todo.write_text(original, encoding="utf-8")
        result = self.run_script("add-todo", "--title", "Invisible", "--goal", "goal", "--verify", "check")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(todo.read_text(encoding="utf-8"), original)
        todo.unlink()
        outside = self.root / "outside.md"
        outside.write_text("keep original\n", encoding="utf-8")
        todo.symlink_to(outside)
        result = self.run_script("add-todo", "--title", "Invalid", "--goal", "goal", "--verify", "check")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(todo.is_symlink())
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep original\n")

    def test_cleanup_rejects_duplicate_records_even_when_bodies_match(self) -> None:
        record = MARKER.replace("2026-09-15", "2020-01-01") + "## Same title\nsame body\n\n"
        original = record + record
        self.lessons.write_text(original, encoding="utf-8")

        result = self.run_script("cleanup", "--force", "--apply")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ID collision", result.stderr)
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), original)
        self.assertFalse((self.aitasks / "archive").exists())

    def test_cleanup_archives_same_title_and_date_with_unique_ids(self) -> None:
        marker = MARKER.replace("2026-09-15", "2020-01-01")
        self.lessons.write_text(
            marker.replace(" -->", " id=unique-first -->") + "## Same title\nfirst body\n\n"
            + marker.replace(" -->", " id=unique-second -->") + "## Same title\nsecond body\n",
            encoding="utf-8",
        )

        result = self.run_script("cleanup", "--force", "--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        archive = next((self.aitasks / "archive").glob("lessons-*.md"))
        archived = archive.read_text(encoding="utf-8")
        self.assertIn("first body", archived)
        self.assertIn("second body", archived)

    def test_cleanup_rejects_changed_record_with_existing_archive_id(self) -> None:
        marker = MARKER.replace("2026-09-15", "2020-01-01").replace(
            " -->", " id=shared-id -->"
        )
        original = marker + "## Same title\nnew body\n"
        archive_text = (
            "# Archived lessons records\n\n"
            "<!-- archived_at=2026-09-14 source=lessons.md -->\n\n"
            + marker + "## Same title\nold body\n"
        )
        self.lessons.write_text(original, encoding="utf-8")
        archive_dir = self.aitasks / "archive"
        archive_dir.mkdir()
        archive_path = archive_dir / "lessons-2026-09-14.md"
        archive_path.write_text(archive_text, encoding="utf-8")

        result = self.run_script("cleanup", "--force", "--apply")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ID collision", result.stderr)
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), original)
        self.assertEqual(archive_path.read_text(encoding="utf-8"), archive_text)

    def test_cleanup_recovers_when_identical_record_is_already_archived(self) -> None:
        marker = MARKER.replace("2026-09-15", "2020-01-01").replace(
            " -->", " id=shared-id -->"
        )
        original = marker + "## Same title\nsame body\n"
        self.lessons.write_text(original, encoding="utf-8")
        archive_dir = self.aitasks / "archive"
        archive_dir.mkdir()
        archive_path = archive_dir / "lessons-2026-09-14.md"
        archive_text = (
            "# Archived lessons records\n\n"
            "<!-- archived_at=2026-09-14 source=lessons.md -->\n\n"
            + original
        )
        archive_path.write_text(archive_text, encoding="utf-8")

        result = self.run_script("cleanup", "--force", "--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), "")
        self.assertEqual(archive_path.read_text(encoding="utf-8"), archive_text)

    def test_archive_reader_ignores_example_marker_inside_fenced_body(self) -> None:
        marker = MARKER.replace("2026-09-15", "2020-01-01")
        archived = (
            "# Archived lessons records\n\n"
            "<!-- archived_at=2026-09-14 source=lessons.md -->\n\n"
            + marker.replace(" -->", " id=archived -->")
            + "## Archived\nExample:\n```md\n"
            + marker.replace(" -->", " id=shared -->")
            + "## Example marker\n```\nPreserved tail.\n"
        )
        current = marker.replace(" -->", " id=shared -->") + "## Actual lesson\nbody\n"
        self.lessons.write_text(current, encoding="utf-8")
        archive_dir = self.aitasks / "archive"
        archive_dir.mkdir()
        archive_path = archive_dir / "lessons-2026-09-14.md"
        archive_path.write_text(archived, encoding="utf-8")

        result = self.run_script("cleanup", "--force", "--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), "")
        self.assertEqual(archive_path.read_text(encoding="utf-8"), archived)
        self.assertIn(
            "## Actual lesson",
            (archive_dir / "lessons-2026-09-15.md").read_text(encoding="utf-8"),
        )

    def test_cleanup_does_not_ignore_unreadable_archive_entry(self) -> None:
        original = MARKER.replace("2026-09-15", "2020-01-01") + "## Old\nbody\n"
        self.lessons.write_text(original, encoding="utf-8")
        archive_dir = self.aitasks / "archive"
        archive_dir.mkdir()
        (archive_dir / "lessons-unreadable.md").mkdir()

        result = self.run_script("cleanup", "--force", "--apply")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cleanup aborted before writing", result.stderr)
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), original)
        self.assertFalse((self.aitasks / ".maintenance.json").exists())

    def test_live_process_lock_is_not_reclaimed_for_old_mtime(self) -> None:
        lock_path = self.aitasks / ".maintenance.lock"
        lock_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
        old_time = time.time() - 3600
        os.utime(lock_path, (old_time, old_time))

        result = self.run_script(
            "cleanup", "--force", "--apply",
            env={**os.environ, "AITASKS_LOCK_TIMEOUT": "0.02"},
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another maintenance process holds", result.stderr)
        self.assertEqual(lock_path.read_text(encoding="utf-8"), f"{os.getpid()}\n")

    def test_fresh_incomplete_lock_is_not_reclaimed(self) -> None:
        lock_path = self.aitasks / ".maintenance.lock"
        lock_path.write_text("", encoding="utf-8")

        result = self.run_script(
            "cleanup", "--force", "--apply",
            env={**os.environ, "AITASKS_LOCK_TIMEOUT": "0.02"},
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another maintenance process holds", result.stderr)
        self.assertTrue(lock_path.exists())

    def test_lock_release_preserves_a_replacement_owned_by_another_process(self) -> None:
        lock_path = self.aitasks / ".maintenance.lock"
        lock = maintenance.MaintenanceLock(lock_path)

        with lock:
            lock_path.unlink()
            lock_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
            # Simulate a filesystem immediately reusing the released inode.
            replacement = lock_path.lstat()
            lock._identity = (replacement.st_dev, replacement.st_ino)

        self.assertTrue(lock_path.exists())

    def test_stale_lock_reclaim_does_not_remove_a_new_owner(self) -> None:
        lock_path = self.aitasks / ".maintenance.lock"
        lock_path.write_text("999999999\n", encoding="utf-8")
        first = maintenance.MaintenanceLock(lock_path, timeout=2, sleep_interval=0.005)
        second = maintenance.MaintenanceLock(lock_path, timeout=2, sleep_interval=0.005)
        stale_checked = threading.Event()
        resume_first = threading.Event()
        first_entered = threading.Event()
        second_entered = threading.Event()
        release_first = threading.Event()
        errors: list[BaseException] = []
        original_is_stale = first.is_stale

        def pause_after_stale_check() -> bool:
            stale = original_is_stale()
            stale_checked.set()
            if not resume_first.wait(2):
                raise TimeoutError("first contender did not resume")
            return stale

        first.is_stale = pause_after_stale_check

        def acquire(lock: maintenance.MaintenanceLock, entered: threading.Event) -> None:
            try:
                with lock:
                    entered.set()
                    if lock is first and not release_first.wait(2):
                        raise TimeoutError("first owner was not released")
            except BaseException as error:
                errors.append(error)

        first_thread = threading.Thread(target=acquire, args=(first, first_entered))
        second_thread = threading.Thread(target=acquire, args=(second, second_entered))
        first_thread.start()
        try:
            self.assertTrue(stale_checked.wait(2))
            second_thread.start()
            self.assertFalse(second_entered.wait(0.05))
            resume_first.set()
            self.assertTrue(first_entered.wait(2))
            self.assertFalse(second_entered.is_set())
            release_first.set()
            self.assertTrue(second_entered.wait(2))
        finally:
            resume_first.set()
            release_first.set()
            first_thread.join(2)
            if second_thread.ident is not None:
                second_thread.join(2)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
