from __future__ import annotations

import json
import importlib.util
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "skills/aitasks-maintenance/scripts/maintain_aitasks.py"


class MemoryWorkflowTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.records = self.root / ".aitasks"
        self.records.mkdir()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), "--project-root", str(self.root),
                               "--today", "2026-11-04", *args],
                              capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

    def result(self, *args):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def lesson(self, name, body="refund rule", pinned=False):
        return (f"<!-- aitasks:lesson id={name} created_at=2026-11-04 last_used_at=- use_count=0 pinned={str(pinned).lower()} -->\n"
                f"## {name}\n\n- 适用范围：refund module\n- 正确做法：{body}\n\n")

    def todo(self, name, body="refund task"):
        return (f"<!-- aitasks:todo id={name} created_at=2026-11-04 status=active completed_at=- -->\n"
                f"## {name}\n\n### 目标与范围\n\n{body}\n\n### 结果\n\n待完成。\n\n")

    def test_context_limits_count_and_serialized_characters_without_full_bodies(self):
        (self.records / "lessons.md").write_text("".join(self.lesson(f"rule{i}", "refund " * 500 + "FULL_BODY_END") for i in range(20)))
        (self.records / "todo.md").write_text("".join(self.todo(f"task{i}", "refund " * 500 + "TODO_BODY_END") for i in range(20)))
        before = self.snapshot()
        result = self.run_cli("context", "--query", "refund", "--max-chars", "1800")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertLessEqual(len(result.stdout), 1800)
        self.assertLessEqual(len(data["lessons"]), 3)
        self.assertLessEqual(len(data["todos"]), 3)
        self.assertGreater(len(data["lessons"]), 0)
        self.assertTrue(data["truncated"])
        self.assertNotIn("FULL_BODY_END", result.stdout)
        self.assertNotIn("TODO_BODY_END", result.stdout)
        self.assertNotIn("used_tasks", result.stdout)
        self.assertEqual(before, self.snapshot())

    def test_context_stamp_is_explicit_and_does_not_hide_context_in_a_new_session(self):
        (self.records / "lessons.md").write_text(self.lesson("refund"))
        first = self.result("context", "--query", "refund")
        same = self.result("context", "--query", "refund", "--since", first["stamp"])
        self.assertTrue(same["unchanged"])
        self.assertNotIn("lessons", same)
        self.assertEqual(len(self.result("context", "--query", "refund")["lessons"]), 1)
        (self.records / "lessons.md").write_text(self.lesson("refund", "updated refund rule"))
        changed = self.result("context", "--query", "refund", "--since", first["stamp"])
        self.assertFalse(changed["unchanged"])
        self.assertNotEqual(changed["stamp"], first["stamp"])

    def test_get_record_reads_one_archived_record_with_a_budget(self):
        archive = self.records / "archive/lessons-2026-10-01.md"
        archive.parent.mkdir()
        archive.write_text(self.lesson("wanted", "refund " * 1000) + self.lesson("other", "OTHER_RECORD"))
        before = self.snapshot()
        result = self.run_cli("get-record", "--kind", "lesson", "--id", "wanted", "--max-chars", "900")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["id"], "wanted")
        self.assertEqual(data["source"]["path"], str(archive.resolve()))
        self.assertTrue(data["truncated"])
        self.assertLessEqual(len(result.stdout), 900)
        self.assertNotIn("OTHER_RECORD", result.stdout)
        self.assertNotIn("aitasks:lesson", data["content"])
        self.assertEqual(before, self.snapshot())

    def test_todo_filter_and_default_limit_are_bounded(self):
        (self.records / "todo.md").write_text("".join(self.todo(f"task{i}", "refund") for i in range(8)) + self.todo("unrelated", "profile"))
        all_active = self.result("list-todos", "--json")
        self.assertEqual(len(all_active["todos"]), 3)
        self.assertTrue(all_active["truncated"])
        filtered = self.result("list-todos", "--query", "profile", "--json", "--limit", "1")
        self.assertEqual([x["id"] for x in filtered["todos"]], ["unrelated"])
        detail = self.result("get-record", "--kind", "todo", "--id", "unrelated")
        self.assertIn("profile", detail["content"])
        self.assertNotIn("## task0", detail["content"])

    def test_context_requires_keywords_and_readonly_queries_create_no_state(self):
        self.assertNotEqual(self.run_cli("context", "--query", "  ").returncode, 0)
        (self.records).rmdir()
        empty = self.result("context", "--query", "refund")
        self.assertEqual(empty["lessons"], [])
        self.assertEqual(empty["todos"], [])
        self.assertFalse(self.records.exists())

    def lesson_args(self, resolution="Preserve offset", cause="Conversion removed offset"):
        return ("--title", "Date offset", "--context", "Date export", "--problem", "Offset lost",
                "--cause", cause, "--resolution", resolution, "--scope", "Export module")

    def observe(self, task, **kwargs):
        return self.result("observe", "--key", "export.offset.loss", "--task-id", task,
                           "--evidence", "export.py:12", *(["--verified"] if kwargs.get("verified", True) else []))

    def test_observation_query_is_bounded_readonly_and_returns_reusable_keys(self):
        self.observe("task-a")
        for index in range(5):
            self.result("observe", "--key", f"export.timeout.{index}", "--task-id", f"other-{index}",
                        "--evidence", "worker.py:3", "--verified")
        before = self.snapshot()
        result = self.run_cli("find-observations", "--query", "export", "--max-chars", "900")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertLessEqual(len(result.stdout), 900)
        self.assertLessEqual(len(data["observations"]), 3)
        self.assertTrue(data["truncated"])
        self.assertEqual(data["total_matches"], 6)
        self.assertNotIn('"tasks"', result.stdout)
        self.assertEqual(self.snapshot(), before)
        selected = self.result("find-observations", "--query", "export offset")["observations"][0]
        self.assertEqual(selected["key"], "export.offset.loss")
        self.assertEqual(selected["decision"], "candidate")
        self.assertEqual(selected["evidence"], "export.py:12")

    def test_observation_key_can_be_reused_by_a_fresh_process_then_promoted_once(self):
        self.observe("task-a")
        selected = self.result("find-observations", "--query", "export offset")["observations"][0]
        ready = self.result("observe", "--key", selected["key"], "--task-id", "task-b", "--evidence", "export.py:20", "--verified")
        self.assertEqual(ready["decision"], "ready")
        lesson = self.result("upsert-lesson", "--key", selected["key"], *self.lesson_args())
        found = self.result("find-observations", "--query", "export offset")["observations"][0]
        self.assertEqual(found["decision"], "recorded")
        self.assertEqual(found["lesson_id"], lesson["id"])
        self.assertEqual(found["count"], 2)
        self.assertEqual((self.records / "lessons.md").read_text().count("aitasks:lesson"), 1)

    def test_observation_candidates_do_not_merge_distinct_causes(self):
        for key in ("export.offset.stripped", "export.offset.converted"):
            self.result("observe", "--key", key, "--task-id", "task-a", "--evidence", "export.py:12", "--verified")
        before = self.snapshot()
        candidates = self.result("find-observations", "--query", "export offset")["observations"]
        self.assertEqual({x["key"] for x in candidates}, {"export.offset.stripped", "export.offset.converted"})
        self.assertEqual(self.snapshot(), before)
        for key in ("export.offset.stripped", "export.offset.converted"):
            self.assertNotEqual(self.run_cli("upsert-lesson", "--key", key, *self.lesson_args()).returncode, 0)

    def test_missing_observation_query_writes_nothing_and_bad_state_is_preserved(self):
        self.records.rmdir()
        self.assertEqual(self.result("find-observations", "--query", "export")["observations"], [])
        self.assertFalse(self.records.exists())
        self.records.mkdir()
        path = self.records / ".observations.json"
        path.write_text('{broken')
        before = self.snapshot()
        self.assertNotEqual(self.run_cli("find-observations", "--query", "export").returncode, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertNotEqual(self.run_cli("find-observations", "--query", "  ").returncode, 0)

    def test_unverified_observation_is_a_noop_and_independent_tasks_control_readiness(self):
        skipped = self.observe("task-a", verified=False)
        self.assertEqual(skipped["decision"], "skip")
        self.assertEqual(self.snapshot(), {})
        first = self.observe("task-a")
        self.assertEqual((first["count"], first["decision"]), (1, "candidate"))
        before = self.snapshot()
        repeated = self.observe("task-a")
        self.assertEqual(repeated["count"], 1)
        self.assertEqual(self.snapshot(), before)
        second = self.observe("task-b")
        self.assertEqual((second["count"], second["decision"]), (2, "ready"))
        self.assertEqual(self.observe("task-c")["count"], 2)
        self.assertFalse((self.records / "lessons.md").exists())
        self.assertLess(len((self.records / ".observations.json").read_text()), 1500)

    def test_promotion_requires_repeat_and_confirmed_cause_and_reuses_linked_lesson(self):
        self.observe("task-a")
        denied = self.run_cli("upsert-lesson", "--key", "export.offset.loss", *self.lesson_args())
        self.assertNotEqual(denied.returncode, 0)
        self.assertFalse((self.records / "lessons.md").exists())
        self.observe("task-b")
        unknown = self.run_cli("upsert-lesson", "--key", "export.offset.loss", *self.lesson_args(cause="未确认"))
        self.assertNotEqual(unknown.returncode, 0)
        promoted = self.result("upsert-lesson", "--key", "export.offset.loss", *self.lesson_args())
        self.assertEqual(promoted["action"], "created")
        self.assertEqual(self.observe("task-c")["lesson_id"], promoted["id"])
        updated = self.result("upsert-lesson", "--key", "export.offset.loss", *self.lesson_args("Keep original timezone"))
        self.assertEqual(updated["id"], promoted["id"])
        self.assertEqual(updated["action"], "updated")
        text = (self.records / "lessons.md").read_text()
        self.assertEqual(text.count("aitasks:lesson"), 1)
        self.assertIn("Keep original timezone", text)
        self.assertIn("- 依据：export.py:12", text)

    def test_explicit_record_bypasses_count_and_upsert_preserves_other_notes(self):
        created = self.result("upsert-lesson", "--explicit", *self.lesson_args(cause="未确认"))
        path = self.records / "lessons.md"
        path.write_text(path.read_text() + "\n- 补充做法：Keep this independent note.\n")
        updated = self.result("upsert-lesson", "--explicit", "--id", created["id"], *self.lesson_args())
        self.assertEqual(updated["id"], created["id"])
        self.assertIn("Keep this independent note", path.read_text())
        self.assertFalse((self.records / ".observations.json").exists())

    def test_distinct_observation_keys_cannot_merge_by_title(self):
        self.observe("task-a")
        self.observe("task-b")
        first = self.result("upsert-lesson", "--key", "export.offset.loss", *self.lesson_args())
        for task in ("task-c", "task-d"):
            self.result("observe", "--key", "export.encoding.loss", "--task-id", task,
                        "--evidence", "export.py:20", "--verified")
        original = (self.records / "lessons.md").read_text()
        result = self.run_cli("upsert-lesson", "--key", "export.encoding.loss", *self.lesson_args(cause="encoding"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.records / "lessons.md").read_text(), original)
        self.assertEqual(self.result("get-record", "--kind", "lesson", "--id", first["id"])["id"], first["id"])
        self.assertIsNone(self.result("find-observations", "--query", "encoding")["observations"][0]["lesson_id"])
        encoding = list(self.lesson_args(cause="encoding"))
        encoding[1] = "Encoding failure"
        second = self.result("upsert-lesson", "--key", "export.encoding.loss", *encoding)
        self.assertNotEqual(first["id"], second["id"])
        self.assertIn("Conversion removed offset", (self.records / "lessons.md").read_text())

    def test_repeated_upsert_preserves_action_contract_and_reports_no_content_change(self):
        created = self.result("upsert-lesson", "--explicit", *self.lesson_args())
        before = (self.records / "lessons.md").read_bytes()
        result = self.result("upsert-lesson", "--explicit", "--id", created["id"], *self.lesson_args())
        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["id"], created["id"])
        self.assertFalse(result["changed"])
        self.assertTrue(result["maintenance_checked"])
        self.assertEqual(before, (self.records / "lessons.md").read_bytes())

    def test_upsert_preserves_free_text_between_fields(self):
        created = self.result("upsert-lesson", "--explicit", *self.lesson_args())
        path = self.records / "lessons.md"
        original = path.read_text().replace("- 问题：", "补充笔记：保留上游兼容。\n\n- 问题：")
        path.write_text(original)
        self.result("upsert-lesson", "--explicit", "--id", created["id"], *self.lesson_args("New resolution"))
        self.assertIn("补充笔记：保留上游兼容。", path.read_text())
        self.assertIn("New resolution", path.read_text())

    def test_upsert_archived_lesson_by_id_keeps_metadata_and_other_records(self):
        archive = self.records / "archive/lessons-2026-11-04.md"
        archive.parent.mkdir()
        archive.write_text(self.lesson("old", "original") + self.lesson("other", "keep other"))
        (self.records / "lessons.md").write_text(self.lesson("expired").replace("2026-11-04", "2020-01-01"))
        result = self.result("upsert-lesson", "--explicit", "--id", "old", *self.lesson_args("Updated rule"))
        self.assertEqual((result["id"], result["action"]), ("old", "updated"))
        self.assertIn("Updated rule", self.result("get-record", "--kind", "lesson", "--id", "old")["content"])
        self.assertIn("keep other", archive.read_text())
        self.assertIn("expired", archive.read_text())

    def test_upsert_rejects_ambiguous_ids_and_preserves_files(self):
        archive = self.records / "archive/lessons-2026-11-04.md"
        archive.parent.mkdir()
        archive.write_text(self.lesson("duplicate", "archive"))
        (self.records / "lessons.md").write_text(self.lesson("duplicate", "active"))
        before = self.snapshot()
        result = self.run_cli("upsert-lesson", "--explicit", "--id", "duplicate", *self.lesson_args())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual({k: v for k, v in self.snapshot().items() if not k.endswith('.guard')},
                         {k: v for k, v in before.items() if not k.endswith('.guard')})

    def test_upsert_rejects_ambiguous_multiline_field_without_writing(self):
        created = self.result("upsert-lesson", "--explicit", *self.lesson_args())
        path = self.records / "lessons.md"
        path.write_text(path.read_text().replace("- 问题：Offset lost", "- 问题：\n\nMultiple lines\n\nExtra note"))
        original = path.read_bytes()
        result = self.run_cli("upsert-lesson", "--explicit", "--id", created["id"], *self.lesson_args())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr)
        self.assertEqual(path.read_bytes(), original)

    def test_upsert_multiline_fence_stays_inside_one_record_and_later_update_is_safe(self):
        created = self.result("upsert-lesson", "--explicit", *self.lesson_args())
        args = self.lesson_args("```md\n## Example\n- 原因：example\n```")
        self.result("upsert-lesson", "--explicit", "--id", created["id"], *args)
        path = self.records / "lessons.md"
        original = path.read_bytes()
        detail = self.result("get-record", "--kind", "lesson", "--id", created["id"])
        self.assertIn("## Example", detail["content"])
        result = self.run_cli("upsert-lesson", "--explicit", "--id", created["id"], *self.lesson_args())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_bytes(), original)

    def test_usage_is_counted_once_per_task_even_when_tasks_interleave(self):
        created = self.result("upsert-lesson", "--explicit", *self.lesson_args())
        for task in ("task-a", "task-b", "task-a", "task-b"):
            marked = self.run_cli("mark-used", "--id", created["id"], "--task-id", task, "--maintain")
            self.assertEqual(marked.returncode, 0, marked.stderr)
        data = self.result("find-lessons", "--query", "Date offset", "--json")
        self.assertEqual(data["matches"][0]["use_count"], 2)
        self.assertEqual(len(data["matches"][0]["metadata"]["used_tasks"].split(",")), 2)

    def test_observation_rejects_raw_logs_and_corrupt_state_without_overwriting(self):
        long_input = self.run_cli("observe", "--key", "export.offset.loss", "--task-id", "task-a",
                                  "--evidence", "x" * 1000, "--verified")
        self.assertNotEqual(long_input.returncode, 0)
        state = self.records / ".observations.json"
        state.write_text("invalid JSON")
        result = self.run_cli("observe", "--key", "export.offset.loss", "--task-id", "task-a",
                              "--evidence", "export.py:12", "--verified")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state.read_text(), "invalid JSON")
        explicit = self.result("upsert-lesson", "--explicit", *self.lesson_args())
        self.assertEqual(explicit["action"], "created")
        self.assertEqual(state.read_text(), "invalid JSON")

    def test_context_ranks_relevant_terms_without_loading_unrelated_pinned_rules(self):
        unrelated = "".join(self.lesson(f"profile{i}", "profile only", pinned=True).replace("refund module", "profile module") for i in range(12))
        (self.records / "lessons.md").write_text(unrelated + self.lesson("refund-timeout", "Handle timeout"))
        context = self.result("context", "--query", "refund timeout")
        self.assertEqual([r["id"] for r in context["lessons"]], ["refund-timeout"])
        self.assertEqual(context["total_lessons"], 1)

    def test_weak_active_match_does_not_hide_specific_archived_lesson(self):
        (self.records / "lessons.md").write_text(self.lesson("generic", "config maintenance").replace("refund module", "config"))
        archive = self.records / "archive/lessons-2026-10-01.md"
        archive.parent.mkdir()
        archive.write_text(self.lesson("超时零值", "config timeout=0 is valid").replace("refund module", "config"))
        before = self.snapshot()
        data = self.result("context", "--query", "config timeout", "--lesson-limit", "1")
        self.assertEqual(data["lessons"][0]["id"], "超时零值")
        self.assertTrue(data["lessons"][0]["archived"])
        self.assertEqual(before, self.snapshot())

    def test_aliases_count_one_concept_and_project_changes_invalidate_stamp(self):
        (self.records / "lessons.md").write_text(self.lesson("超时", "preserve zero"))
        data = self.result("context", "--query", "timeout")
        self.assertEqual([r["id"] for r in data["lessons"]], ["超时"])
        (self.records / "search-aliases.json").write_text(json.dumps([["deadline", "timeout", "超时"]]))
        changed = self.result("context", "--query", "timeout", "--since", data["stamp"])
        self.assertFalse(changed["unchanged"])
        self.assertEqual(len(self.result("context", "--query", "deadline")["lessons"]), 1)
        (self.records / "search-aliases.json").write_text('{broken')
        before = self.snapshot()
        self.assertNotEqual(self.run_cli("context", "--query", "timeout").returncode, 0)
        self.assertEqual(before, self.snapshot())

    def test_alias_stacking_does_not_outrank_better_concept_coverage(self):
        (self.records / "lessons.md").write_text(
            self.lesson("timeout 超时", "only one concept").replace("refund module", "config")
            + self.lesson("specific", "timeout refund").replace("refund module", "config"))
        data = self.result("context", "--query", "timeout 超时 refund", "--lesson-limit", "1")
        self.assertEqual(data["lessons"][0]["id"], "specific")

    def test_inactive_lessons_are_excluded_but_detail_explains_replacement(self):
        old = self.lesson("old", "retry rule").replace("pinned=false", "pinned=false status=superseded superseded_by=current")
        retired = self.lesson("retired", "retry rule").replace("pinned=false", "pinned=false status=retired")
        (self.records / "lessons.md").write_text(old + retired + self.lesson("current", "retry rule"))
        self.assertEqual([x["id"] for x in self.result("context", "--query", "retry")["lessons"]], ["current"])
        self.assertEqual([x["title"] for x in self.result("find-lessons", "--query", "retry", "--json")["matches"]], ["current"])
        detail = self.result("get-record", "--kind", "lesson", "--id", "old")
        self.assertEqual(detail["status"], "superseded")
        self.assertEqual(detail["superseded_by"], "current")

    def test_status_change_is_reversible_and_preserves_unrelated_bytes_and_mode(self):
        path = self.records / "lessons.md"
        other = self.lesson("current", "retry rule")
        path.write_bytes((self.lesson("old", "retry rule") + other).replace("\n", "\r\n").encode())
        path.chmod(0o640)
        self.result("set-lesson-status", "--id", "old", "--status", "superseded", "--superseded-by", "current", "--reason", "CONTRACT.md updated")
        self.assertIn(other.replace("\n", "\r\n").encode(), path.read_bytes())
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertNotIn(b"\n", path.read_bytes().replace(b"\r\n", b""))
        self.assertEqual(self.result("get-record", "--kind", "lesson", "--id", "old")["superseded_by"], "current")
        self.result("set-lesson-status", "--id", "old", "--status", "active", "--reason", "Rechecked current contract")
        self.assertEqual(len(self.result("context", "--query", "retry")["lessons"]), 2)
        self.assertIsNone(self.result("get-record", "--kind", "lesson", "--id", "old")["superseded_by"])

    def test_supersession_requires_existing_active_distinct_target(self):
        (self.records / "lessons.md").write_text(self.lesson("old"))
        before = (self.records / "lessons.md").read_bytes()
        for target in ("old", "missing"):
            result = self.run_cli("set-lesson-status", "--id", "old", "--status", "superseded", "--superseded-by", target, "--reason", "Updated contract")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(before, (self.records / "lessons.md").read_bytes())
            self.assertFalse((self.records / ".maintenance.json").exists())

    def test_archived_lesson_usage_survives_maintenance_appending_to_same_archive(self):
        archive = self.records / "archive/lessons-2026-11-04.md"
        archive.parent.mkdir()
        archive.write_text(self.lesson("archived"))
        (self.records / "lessons.md").write_text(self.lesson("expired").replace("2026-11-04", "2020-01-01"))
        for _ in range(2):
            marked = self.run_cli("mark-used", "--id", "archived", "--task-id", "task-a", "--maintain")
            self.assertEqual(marked.returncode, 0, marked.stderr)
        data = self.result("find-lessons", "--query", "archived", "--json")
        self.assertEqual(data["matches"][0]["use_count"], 1)
        self.assertIn("expired", archive.read_text())
        self.assertNotIn("expired", (self.records / "lessons.md").read_text())

    def test_archived_status_update_survives_same_day_maintenance_and_can_be_audited(self):
        archive = self.records / "archive/lessons-2026-11-04.md"
        archive.parent.mkdir()
        archive.write_text(self.lesson("old", "retry rule"))
        (self.records / "lessons.md").write_text(self.lesson("expired").replace("2026-11-04", "2020-01-01"))
        self.result("set-lesson-status", "--id", "old", "--status", "retired", "--reason", "No longer applies")
        detail = self.result("get-record", "--kind", "lesson", "--id", "old")
        self.assertEqual(detail["status"], "retired")
        self.assertIn("expired", archive.read_text())
        self.assertEqual(self.result("context", "--query", "retry")["lessons"], [])
        self.assertEqual(len(self.result("find-lessons", "--query", "retry", "--include-inactive", "--json")["matches"]), 1)

    def test_legacy_lesson_can_be_read_by_context_id_without_metadata_migration(self):
        path = self.records / "lessons.md"
        original = "# Lessons\n\n## Date export\nPreserve offset.\n\n## Other\nUnrelated.\n"
        path.write_text(original)
        context = self.result("context", "--query", "offset")
        detail = self.result("get-record", "--kind", "lesson", "--id", context["lessons"][0]["id"])
        self.assertIn("Preserve offset", detail["content"])
        self.assertNotIn("## Other", detail["content"])
        self.assertEqual(path.read_text(), original)

    def test_concurrent_independent_observations_do_not_lose_a_task(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.observe, ("task-a", "task-b")))
        self.assertEqual(sorted(r["count"] for r in results), [1, 2])
        state = json.loads((self.records / ".observations.json").read_text())
        row = next(iter(state["observations"].values()))
        self.assertEqual(set(row["tasks"]), {"task-a", "task-b"})

    def test_promotion_retry_after_link_write_failure_does_not_duplicate_lesson(self):
        self.observe("task-a")
        self.observe("task-b")
        spec = importlib.util.spec_from_file_location("memory_recovery", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        write = module.atomic_write
        def fail_link(path, content, **kwargs):
            if path.name == ".observations.json":
                raise OSError("injected link write failure")
            return write(path, content, **kwargs)
        arguments = [str(SCRIPT), "--project-root", str(self.root), "--today", "2026-11-04",
                     "upsert-lesson", "--key", "export.offset.loss", *self.lesson_args()]
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(module, "atomic_write", fail_link), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                module.main()
        original = (self.records / "lessons.md").read_text()
        retried = self.result("upsert-lesson", "--key", "export.offset.loss", *self.lesson_args())
        self.assertEqual(retried["action"], "updated")
        self.assertIn("id=" + retried["id"], original)
        self.assertEqual((self.records / "lessons.md").read_text().count("aitasks:lesson"), 1)


if __name__ == "__main__":
    unittest.main()
