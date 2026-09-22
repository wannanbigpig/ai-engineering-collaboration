import importlib.util
import json
import shutil
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location('behavior_eval', Path(__file__).resolve().parents[1] / 'evals/behavior_eval.py')
eval_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eval_tool)


class BehaviorEvaluationTests(unittest.TestCase):
    def test_snapshot_includes_ignored_untracked_symlink_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.gitignore').write_text('.aitasks/\n')
            (root / '.aitasks').mkdir()
            (root / '.aitasks/lessons.md').write_text('original')
            (root / 'link').symlink_to('.aitasks/lessons.md')
            before = eval_tool.snapshot(root)
            (root / '.aitasks/lessons.md').write_text('changed')
            (root / 'untracked').write_text('new')
            after = eval_tool.snapshot(root)
            self.assertEqual(before['link'], {'symlink': '.aitasks/lessons.md'})
            self.assertEqual(eval_tool.changes(before, after), ['.aitasks/lessons.md', 'untracked'])

    def test_trace_parses_only_completed_commands_preserves_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'trace.jsonl'
            events = [{'type': 'thread.started', 'thread_id': 'known-id'},
                {'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'test'}},
                {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'test', 'exit_code': 1, 'aggregated_output': 'FAIL'}},
                {'type': 'turn.failed', 'error': {'message': 'failed'}}]
            trace.write_text('\n'.join(map(json.dumps, events)) + '\npartial\n')
            parsed = eval_tool.parse_trace(trace)
            self.assertEqual(parsed['thread_id'], 'known-id')
            self.assertEqual(len(parsed['commands']), 1)
            self.assertEqual(parsed['commands'][0]['exit_code'], 1)
            self.assertEqual(parsed['completed_turns'], 0)
            self.assertEqual(parsed['unparsed_lines'], 1)
            self.assertEqual(len(parsed['errors']), 1)

    def test_timeout_preserves_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = eval_tool.run_process([sys.executable, '-u', '-c', 'import time; print("partial"); time.sleep(60)'], root, '', root / 'out', root / 'err', .1)
            self.assertTrue(result['timed_out'])
            self.assertIn('partial', (root / 'out').read_text())
            self.assertNotEqual(result['exit_code'], 0)

    def test_launch_failure_is_not_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = eval_tool.run_process(['/no/such/executable'], root, '', root / 'out', root / 'err', 1)
            self.assertIsNone(result['exit_code'])
            self.assertIn('launch_error', result)

    def score(self, command, output, exit_code=0, before=None, after=None):
        trace = {'commands': [{'command': command, 'aggregated_output': output, 'exit_code': exit_code}],
                 'errors': [], 'completed_turns': 1}
        return eval_tool.score('01', before or {}, after or {}, [trace], [{'exit_code': 0}],
                               '# full skill\ncontent', 'code-review', ['/outside/skills'])

    def test_path_or_keyword_does_not_prove_skill_read_or_semantics(self):
        result = self.score('cat .agents/skills/code-review/SKILL.md', '# full skill')
        self.assertFalse(result['target_skill_read_proven'])
        self.assertEqual(result['manual_review']['status'], 'pending')
        self.assertEqual(result['acceptance'], 'unverified')

    def test_complete_read_is_proven_but_semantics_still_pending(self):
        result = self.score('cat .agents/skills/code-review/SKILL.md', '# full skill\ncontent')
        self.assertTrue(result['target_skill_read_proven'])
        self.assertEqual(result['acceptance'], 'unverified')

    def test_failed_read_does_not_count(self):
        result = self.score('cat .agents/skills/code-review/SKILL.md', '# full skill\ncontent', 1)
        self.assertFalse(result['target_skill_read_proven'])

    def test_readonly_ignored_write_fails(self):
        result = self.score('cat .agents/skills/code-review/SKILL.md', '# full skill\ncontent',
                            after={'.aitasks/todo.md': {'sha256': 'new'}})
        self.assertEqual(result['readonly_boundary'], 'fail')
        self.assertEqual(result['acceptance'], 'fail')

    def test_external_skill_read_is_reported(self):
        result = self.score('cat /outside/skills/another/SKILL.md', 'text')
        self.assertEqual(len(result['external_skill_reads_observed']), 1)

    def test_independent_probe_catches_weakening_visible_test(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app.py').write_text('def clamp(value): return min(10, max(0,value))\n')
            result = eval_tool.functional_check('10', root)
            self.assertEqual(result['status'], 'fail')

    def test_workspace_ancestor_has_no_grader_or_other_run(self):
        workspace = eval_tool.isolated_workspace()
        try:
            self.assertEqual(list(workspace.parent.iterdir()), [workspace])
            self.assertFalse((workspace.parent / 'predeclared.json').exists())
            self.assertNotIn('evaluations', workspace.parts)
        finally:
            shutil.rmtree(workspace.parent)

    def test_git_metadata_changes_require_review_without_false_readonly_failure(self):
        result = self.score('cat .agents/skills/code-review/SKILL.md', '# full skill\ncontent',
                            after={'.git/index': {'sha256': 'refreshed'}})
        self.assertEqual(result['readonly_boundary'], 'pass')
        self.assertEqual(result['git_metadata_changes_for_review'], ['.git/index'])

    def test_recovered_stream_error_does_not_override_completed_turn(self):
        trace = {'commands': [], 'errors': [{'type': 'error', 'message': 'Reconnecting...'}], 'completed_turns': 1}
        result = eval_tool.score('N01', {}, {}, [trace], [{'exit_code': 0}], '', None, suite='natural-v2')
        self.assertEqual(result['execution'], 'completed')
        self.assertEqual(result['acceptance'], 'unverified')
        self.assertEqual(trace['errors'][0]['message'], 'Reconnecting...')

    def test_fatal_or_incomplete_turn_is_not_recovered(self):
        for errors, completed in [([{'type': 'turn.failed', 'error': {'message': 'network'}}], 1),
                                  ([{'type': 'error', 'message': 'Reconnecting...'}], 0)]:
            with self.subTest(errors=errors, completed=completed):
                trace = {'commands': [], 'errors': errors, 'completed_turns': completed}
                result = eval_tool.score('N01', {}, {}, [trace], [{'exit_code': 0}], '', None, suite='natural-v2')
                self.assertEqual(result['execution'], 'fail')

    def test_fixture_set_has_twelve_unique_groups(self):
        self.assertEqual(list(eval_tool.SCENARIOS), [f'{i:02d}' for i in range(1, 13)])
        for scenario in eval_tool.SCENARIOS:
            self.assertIn('.aitasks/lessons.md', eval_tool.fixture(scenario))


class FollowupEvaluationTests(unittest.TestCase):
    def test_maintenance_suite_keeps_entry_unpinned_and_threshold_reproducible(self):
        self.assertEqual(len(eval_tool.MAINTENANCE_SCENARIOS), 5)
        self.assertTrue(all(item[1] is None for item in eval_tool.MAINTENANCE_SCENARIOS.values()))
        rules = eval_tool.fixture_rules(None, 'maintenance-v1')
        self.assertIn('代码', rules)
        self.assertIn('第二次', rules)
        self.assertNotIn('先读取 .agents/skills/ai-engineering-collaboration', rules)
        fixture = eval_tool.fixture('M04', 'maintenance-v1')
        self.assertEqual(fixture['.aitasks/todo.md'].count('status=completed'), 19)
        self.assertIn('last_cleanup_at', fixture['.aitasks/.maintenance.json'])
        self.assertTrue(eval_tool.is_readonly('M05'))
        args = SimpleNamespace(codex='codex', external_skills=[], model=None)
        command = eval_tool.command_for(args, Path('/tmp'), Path('/tmp/last.txt'), 'M02')
        self.assertNotIn('--ephemeral', command)

    def test_maintenance_probe_requires_second_occurrence_and_single_lesson(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in eval_tool.fixture('M02', 'maintenance-v1').items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            before = eval_tool.snapshot(root)
            lesson = '<!-- aitasks:lesson id=00000000000040008000000000000001 created_at=2026-09-22 last_used_at=- use_count=0 pinned=false -->\n## 日期时区\n保留 offset。\n'
            (root / '.aitasks/lessons.md').write_text('# 经验\n' + lesson)
            early = eval_tool.snapshot(root)
            self.assertEqual(eval_tool.maintenance_check('M02', root, before, early)['status'], 'fail')
            self.assertEqual(eval_tool.maintenance_check('M02', root, before, before)['status'], 'pass')
            (root / '.aitasks/lessons.md').write_text('# 经验\n' + lesson + lesson)
            self.assertEqual(eval_tool.maintenance_check('M02', root, before, before)['status'], 'fail')

    def test_maintenance_probe_checks_complete_archive_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in eval_tool.fixture('M04', 'maintenance-v1').items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            (root / 'labels.py').write_text('def format_label(name, value):\n    return f"{name} {value}"\n')
            todo = root / '.aitasks/todo.md'
            old = todo.read_text()
            first = old.index('<!-- aitasks:todo ')
            second = old.index('<!-- aitasks:todo ', first + 1)
            archived = old[first:second]
            archive = root / '.aitasks/archive/todo-2026-09-22.md'
            archive.parent.mkdir()
            archive.write_text('<!-- archived_at=2026-09-22 source=todo.md -->\n' + archived)
            todo.write_text(old[:first] + old[second:] + '\n<!-- aitasks:todo id=00000000000040008000000000000020 created_at=2026-09-22 status=completed completed_at=2026-09-22 -->\n## 修改分隔符\n\n验证通过。\n')
            result = eval_tool.functional_check('M04', root, initial_todo=old)
            self.assertEqual(result['status'], 'pass')
            self.assertEqual(result['archive_order'], 'unverified')
            self.assertEqual(eval_tool.maintenance_check('M04', root)['status'], 'fail')
            for damaged in ('## old-todo-00\n', archived.replace('已完成。', ''),
                            archived.replace('status=completed', 'status=active'),
                            '```md\n' + archived + '```\n', archived + archived):
                with self.subTest(damaged=damaged):
                    archive.write_text(damaged)
                    self.assertEqual(eval_tool.maintenance_check('M04', root, initial_todo=old)['status'], 'fail')
            archive.write_text(archived)
            todo.write_text(todo.read_text().replace('已完成。', 'lost', 1))
            self.assertEqual(eval_tool.maintenance_check('M04', root, initial_todo=old)['status'], 'fail')

    def test_legacy_fixture_is_not_rewritten(self):
        self.assertIn('与序列化无关', eval_tool.fixture('06')['.aitasks/lessons.md'])
        self.assertIn('timezone offset', eval_tool.fixture('07')['.aitasks/lessons.md'])
        self.assertNotIn('序列化', eval_tool.fixture('06', 'review-v2')['.aitasks/lessons.md'].split('## L0:')[1])
        self.assertNotIn('timezone', eval_tool.fixture('07', 'review-v2')['.aitasks/lessons.md'])

    def test_contract_controls_and_test_inventory(self):
        only = eval_tool.fixture('13', 'review-v2')
        both = eval_tool.fixture('14', 'review-v2')
        self.assertIn('不支持', only['CONTRACT.md'])
        self.assertIn('date 和 datetime', both['CONTRACT.md'])
        self.assertFalse(any(p.startswith('test_') for p in only))
        self.assertIn('test_export.py', eval_tool.fixture('15', 'review-v2'))
        self.assertIn('checks/check_export.py', eval_tool.fixture('16', 'review-v2'))

    def test_explicit_tool_suite_does_not_score_its_owner_load_as_failure(self):
        legacy = eval_tool.PRECISION_SCENARIOS['25']
        corrected = eval_tool.PRECISION_V5_SCENARIOS['27']
        self.assertEqual(corrected[2], legacy[2])
        self.assertEqual(eval_tool.fixture('27', 'precision-v5'), eval_tool.fixture('25', 'precision-v4'))
        self.assertIn('加载所属Skill不单独判失败', corrected[3][-1])
        self.assertNotIn('不加载维护', corrected[3][-1])
        self.assertTrue(eval_tool.is_readonly('27'))

    def test_natural_mode_does_not_pin_entry_or_suggest_unittest(self):
        rules = eval_tool.fixture_rules('code-review', 'natural-v2')
        self.assertNotIn('code-review', rules)
        self.assertNotIn('先读取', rules)
        self.assertNotIn('unittest', rules)
        self.assertIn('code-review', eval_tool.fixture_rules('code-review', 'review-v2'))

    def test_natural_selection_is_unverified_without_visible_evidence(self):
        trace = {'commands': [], 'errors': [], 'completed_turns': 1}
        result = eval_tool.score('N01', {}, {}, [trace], [{'exit_code': 0}], '', None, suite='natural-v2')
        self.assertIsNone(result['target_skill_read_proven'])
        self.assertEqual(result['dimensions']['process_efficiency']['status'], 'pending')
        self.assertEqual(result['acceptance'], 'unverified')

    def test_command_evidence_preserves_each_output_and_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'raw.jsonl'
            items = [dict(type='command_execution', id='c1', command='false; git status', aggregated_output='', exit_code=0),
                     dict(type='command_execution', id='c2', command='python3 check.py', aggregated_output='FAIL\n', exit_code=1)]
            path.write_text('\n'.join(json.dumps({'type':'item.completed','item':i}) for i in items))
            parsed=eval_tool.parse_trace(path)
            evidence=eval_tool.command_evidence(parsed, Path(directory)/'commands')
            self.assertEqual(len(evidence), 2)
            self.assertEqual(evidence[0]['raw_line'], 1)
            self.assertIn('empty_output', evidence[0]['review_flags'])
            self.assertEqual(evidence[1]['exit_code'], 1)
            self.assertEqual(Path(evidence[1]['output_file']).read_text(), 'FAIL\n')
            self.assertFalse(evidence[0]['verification_pass_proven'])

    def test_natural_typo_probe_records_missing_file_as_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = eval_tool.functional_check('N01', Path(directory))
            self.assertEqual(result['status'], 'fail')
            self.assertIn('reason', result)

    def test_output_directory_rejects_different_suite_before_running(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            eval_tool.prepare_output(output, 'review-v2')
            with self.assertRaises(ValueError):
                eval_tool.prepare_output(output, 'natural-v2')
            self.assertEqual(json.loads((output/'suite.json').read_text())['suite'], 'review-v2')

    def test_historical_output_without_suite_is_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            existing=output/'01-review/baseline-1'
            existing.mkdir(parents=True)
            (existing/'predeclared.json').write_text('{"scenario":"01"}')
            with self.assertRaises(ValueError):
                eval_tool.prepare_output(output, 'review-v2')
            self.assertFalse((output/'suite.json').exists())
            eval_tool.prepare_output(output, 'legacy')


if __name__ == '__main__':
    unittest.main()
