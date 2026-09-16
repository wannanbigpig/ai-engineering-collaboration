from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills/aitasks-maintenance/scripts/maintain_aitasks.py"
)
MARKER = (
    "<!-- aitasks:lesson created_at=2026-09-15 "
    "last_used_at=- use_count=0 pinned=false -->\n"
)


class MaintainAitasksTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.aitasks = self.root / ".aitasks"
        self.aitasks.mkdir()
        self.lessons = self.aitasks / "lessons.md"

    def run_script(self, *arguments: str) -> subprocess.CompletedProcess[str]:
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
        )

    def find(self, query: str, *arguments: str) -> str:
        result = self.run_script("find-lessons", "--query", query, *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

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
        self.assertEqual(json.loads(self.find("不存在", "--json")), {"matches": []})
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
        self.assertEqual(self.find("keyword", "--limit", "2").splitlines(), lines[:2])

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


if __name__ == "__main__":
    unittest.main()
