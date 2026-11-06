import importlib.util
import copy
from contextlib import redirect_stdout
import io
import json
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('behavior_eval', Path(__file__).resolve().parents[1] / 'evals/behavior_eval.py')
eval_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eval_tool)


class BehaviorEvaluationTests(unittest.TestCase):
    def test_pair_cost_gate_preserves_required_evidence_without_blocking_advisory_review(self):
        batch = {'batch_id': 'batch', 'identity': {'variants': ['baseline', 'candidate']}}
        for boundary, probe, expected in (
                ('pass', {'status': 'unverified'}, 'eligible'),
                ('pass', {'status': 'unverified', 'required_evidence_unverified': True}, 'ineligible'),
                ('unverified', {'status': 'pass'}, 'ineligible'),
                ('pass', {'status': 'unverified', 'memory_flow': {'status': 'unverified'}}, 'ineligible')):
            with self.subTest(boundary=boundary, probe=probe):
                results = [{'batch_id': 'batch', 'suite': 'memory-v2', 'scenario': 'R03',
                    'variant': variant, 'repetition': 1, 'execution': 'completed',
                    'readonly_boundary': boundary, 'contract_probe': probe,
                    '_batch_provenance': True, 'review': {'status': 'unverified',
                    'dimensions': {name: {'status': 'fail' if name == 'process_efficiency' else 'pass'}
                                   for name in eval_tool.REVIEW_DIMENSIONS}}}
                    for variant in ('baseline', 'candidate')]
                pair = eval_tool.pair_reports(results, batch, 'locked')[0]
                self.assertEqual(pair['comparison']['status'], expected)

    def test_review_cannot_promote_unverified_required_machine_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = Path(directory)
            (instance / 'trace.txt').write_text('Observed run evidence\n')
            review = {'schema_version': 1, 'reviewer': {'kind': 'agent', 'id': 'reviewer'},
                      'dimensions': {name: {'status': 'pass', 'reason': 'Reviewed the trace',
                                           'evidence': [{'path': 'trace.txt', 'line': 1}]}
                                     for name in eval_tool.REVIEW_DIMENSIONS}}
            (instance / 'review.json').write_text(json.dumps(review))
            for probe, expected in (({'status': 'pass'}, 'pass'),
                                    ({'status': 'not_applicable'}, 'pass'),
                                    ({'status': 'unverified'}, 'pass'),
                                    ({'status': 'unverified', 'required_evidence_unverified': True}, 'unverified'),
                                    ({'status': 'unverified', 'memory_flow': {'status': 'unverified'}}, 'unverified'),
                                    ({'status': 'fail'}, 'fail')):
                with self.subTest(probe=probe):
                    machine = {'execution': 'completed', 'acceptance': 'unverified',
                               'readonly_boundary': 'not_applicable',
                               'contract_probe': probe}
                    original = copy.deepcopy(machine)
                    result = eval_tool.independent_review(instance, machine)
                    self.assertEqual(result['status'], expected)
                    self.assertEqual(machine, original)

    def test_repeat_memory_requires_both_thread_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, workspace = root/'first', root/'workspace'
            last = workspace/'.aitasks'
            first.mkdir()
            last.mkdir(parents=True)
            (first/'.observations.json').write_text(json.dumps({'observations': {'cause': {'tasks': ['t1'], 'lesson_id': None}}}))
            (last/'.observations.json').write_text(json.dumps({'observations': {'cause': {'tasks': ['t1', 't2'], 'lesson_id': 'lesson1'}}}))
            (first/'lessons.md').write_text('# Lessons\n')
            (last/'lessons.md').write_text('<!-- aitasks:lesson id=lesson1 -->\n## Keep offset\n')
            todo = lambda identity: f'<!-- aitasks:todo id={identity} status=completed -->\n## {identity}\nDone.\n'
            (first/'todo.md').write_text(todo('t1'))
            (last/'todo.md').write_text(todo('t1') + todo('t2'))
            for identities, expected in ((('one', None), 'unverified'), ((None, 'two'), 'unverified'),
                                         (('one', 'one'), 'fail'), (('one', 'two'), 'pass')):
                with self.subTest(identities=identities):
                    traces = [{'thread_id': identity} for identity in identities]
                    self.assertEqual(eval_tool.repeat_memory_check(workspace, first, traces)['status'], expected)

    def test_no_skill_control_has_no_local_package_or_pinned_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root/'workspace'
            workspace.mkdir()
            args = SimpleNamespace(suite='natural-v2', output=root/'out', codex='unused',
                                   external_skills=[], model=None, timeout=5)
            def completed(command, cwd, prompt, trace_path, stderr_path, timeout):
                self.assertFalse((cwd/'.agents').exists())
                self.assertNotIn('Skill', (cwd/'AGENTS.md').read_text())
                trace_path.write_text(json.dumps({'type': 'turn.completed', 'usage': {}}) + '\n')
                stderr_path.write_text('')
                return {'exit_code': 0, 'timed_out': False}
            with patch.object(eval_tool, 'isolated_workspace', return_value=workspace), \
                 patch.object(eval_tool, 'run_process', side_effect=completed):
                result = eval_tool.run_case(args, None, 'no-skill', 'N02', 1)
            self.assertEqual(result['local_skill_reads_proven'], [])
            instance = args.output/'N02-explain/no-skill-1'
            declaration = json.loads((instance/'predeclared.json').read_text())
            self.assertIsNone(declaration['source'])
            self.assertEqual(declaration['source_skills'], {})
            self.assertEqual(eval_tool.report(args.output)['runs'][0]['variant'], 'no-skill')
            (instance/'result.json').unlink()
            self.assertEqual(eval_tool.report(args.output)['execution_incomplete'], 1)

    def test_no_skill_control_rejects_forced_workflows_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suite, scenario in (('legacy', '02'), ('maintenance-v1', 'M01'),
                                    ('memory-v2', 'R02'), ('frontend-ui-v1', 'F05')):
                with self.subTest(suite=suite), self.assertRaises(ValueError):
                    eval_tool.run_case(SimpleNamespace(suite=suite, output=root), None, 'no-skill', scenario, 1)
            self.assertEqual(list(root.iterdir()), [])

    def test_cli_schedules_three_controls_and_preserves_source_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('baseline', 'candidate'):
                (root/name/'skills').mkdir(parents=True)
            scheduled = []
            def run_case(args, source, variant, scenario, repetition):
                scheduled.append((source, variant, scenario, repetition))
                return {'execution': 'completed'}
            command = ['behavior_eval.py', 'run', '--suite', 'selection-v1', '--scenarios', 'S01',
                       '--baseline', str(root/'baseline'), '--candidate', str(root/'candidate'),
                       '--output', str(root/'out'), '--include-no-skill', '--repetitions', '2']
            with patch.object(sys, 'argv', command), patch.object(eval_tool, 'run_case', side_effect=run_case), \
                 patch.object(eval_tool, 'discover_external_skills', return_value=[]), redirect_stdout(io.StringIO()):
                eval_tool.main()
            self.assertEqual([row[1] for row in scheduled], ['baseline', 'candidate', 'no-skill', 'no-skill', 'candidate', 'baseline'])
            self.assertTrue(all(source is None for source, variant, _, _ in scheduled if variant == 'no-skill'))

    def test_selection_splits_do_not_leak_grading_into_inputs(self):
        development = eval_tool.select_scenarios('selection-v1')
        holdout = eval_tool.select_scenarios('selection-v1', split='holdout')
        self.assertTrue(development and holdout)
        self.assertTrue(set(development).isdisjoint(holdout))
        self.assertEqual(set(development + holdout), set(eval_tool.SUITES['selection-v1']))
        self.assertEqual(eval_tool.select_scenarios('selection-v1', 'S07'), ['S07'])
        with self.assertRaises(ValueError):
            eval_tool.select_scenarios('selection-v1', 'S07', 'development')
        with self.assertRaises(ValueError):
            eval_tool.select_scenarios('legacy', split='holdout')
        for scenario in development + holdout:
            name, entry, prompt, criteria = eval_tool.SUITES['selection-v1'][scenario]
            self.assertIsNone(entry)
            files = eval_tool.fixture(scenario, 'selection-v1')
            raw = '\n'.join(files.values()) + eval_tool.fixture_rules(entry, 'selection-v1')
            self.assertNotIn('predeclared', raw)
            self.assertTrue(all(criterion not in raw for criterion in criteria))
        self.assertIn('config.ts', eval_tool.fixture('S03', 'selection-v1'))
        self.assertIn('retry.go', eval_tool.fixture('S07', 'selection-v1'))

    def test_memory_flow_unknown_does_not_leave_combined_probe_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(suite='memory-v2', output=Path(directory), codex='unused',
                                   external_skills=[], model=None, timeout=5)
            def completed(command, workspace, prompt, trace_path, stderr_path, timeout):
                trace_path.write_text(json.dumps({'type': 'turn.completed', 'usage': {}}) + '\n')
                stderr_path.write_text('')
                return {'exit_code': 0, 'timed_out': False}
            with patch.object(eval_tool, 'run_process', side_effect=completed), \
                 patch.object(eval_tool, 'functional_check', return_value={'status': 'pass'}), \
                 patch.object(eval_tool, 'repeat_memory_check', return_value={'status': 'unverified'}):
                result = eval_tool.run_case(args, Path(__file__).resolve().parents[1], 'candidate', 'R03', 1)
            self.assertEqual(result['execution'], 'completed')
            self.assertEqual(result['contract_probe']['status'], 'unverified')
            self.assertEqual(result['acceptance'], 'unverified')

    def test_independent_review_requires_evidence_and_does_not_rewrite_machine_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            instance = output/'S01-explain/candidate-1'
            instance.mkdir(parents=True)
            machine = {'scenario': 'S01', 'suite': 'selection-v1', 'variant': 'candidate', 'repetition': 1,
                       'execution': 'completed', 'target_skill_read_proven': None,
                       'readonly_boundary': 'pass', 'contract_probe': {'status': 'not_applicable'},
                       'command_count': 1, 'acceptance': 'unverified'}
            (instance/'result.json').write_text(json.dumps(machine))
            (instance/'trace-1.jsonl').write_text('observed evidence\n')
            review = {'schema_version': 1, 'reviewer': {'kind': 'agent', 'id': 'independent-reviewer'},
                      'dimensions': {name: {'status': 'pass', 'reason': 'Observed in the trace',
                                           'evidence': [{'path': 'trace-1.jsonl', 'line': 1}]}
                                     for name in eval_tool.REVIEW_DIMENSIONS}}
            (instance/'review.json').write_text(json.dumps(review))
            summary = eval_tool.report(output)
            self.assertEqual(summary['runs'][0]['review']['status'], 'pass')
            self.assertEqual(summary['runs'][0]['review']['reviewer']['kind'], 'agent')
            self.assertEqual(json.loads((instance/'result.json').read_text()), machine)
            review['dimensions']['authorization']['evidence'] = []
            (instance/'review.json').write_text(json.dumps(review))
            self.assertEqual(eval_tool.report(output)['runs'][0]['review']['status'], 'invalid')
            review['dimensions']['authorization']['evidence'] = [{'path': '../outside.txt', 'line': 1}]
            (instance/'review.json').write_text(json.dumps(review))
            self.assertEqual(eval_tool.report(output)['runs'][0]['review']['status'], 'invalid')
            review['dimensions']['authorization']['evidence'] = [{'path': 'trace-1.jsonl', 'line': 2}]
            (instance/'review.json').write_text(json.dumps(review))
            self.assertEqual(eval_tool.report(output)['runs'][0]['review']['status'], 'invalid')
            review['dimensions']['authorization']['evidence'] = [{'path': 'trace-1.jsonl', 'line': 1}]
            review['dimensions']['evaluation_validity']['status'] = 'unverified'
            (instance/'review.json').write_text(json.dumps(review))
            self.assertEqual(eval_tool.report(output)['runs'][0]['review']['status'], 'unverified')
            review['dimensions']['evaluation_validity']['status'] = 'not_applicable'
            (instance/'review.json').write_text(json.dumps(review))
            self.assertEqual(eval_tool.report(output)['runs'][0]['review']['status'], 'invalid')
            review['dimensions']['evaluation_validity']['status'] = 'pass'
            review['reviewer']['kind'] = 'human'
            (instance/'review.json').write_text(json.dumps(review))
            machine['acceptance'] = 'fail'
            (instance/'result.json').write_text(json.dumps(machine))
            self.assertEqual(eval_tool.report(output)['runs'][0]['review']['status'], 'fail')

    def test_repeat_fixture_adds_raw_second_task_and_preserves_first_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repaired = 'def csv_value(value):\n    return value.isoformat()\n'
            (root/'export.py').write_text(repaired)
            (root/'test_export.py').write_text(eval_tool.memory_fixture('R03')['test_export.py'])
            eval_tool.add_repeat_task(root)
            self.assertTrue((root/'export.py').read_text().startswith(repaired))
            self.assertEqual(eval_tool.functional_check('R03', root)['status'], 'fail')
            (root/'export.py').write_text(repaired + '\ndef json_value(value):\n    return value.isoformat()\n')
            self.assertEqual(eval_tool.functional_check('R03', root)['status'], 'pass')

    def test_repeat_uses_fresh_cli_sessions_without_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(suite='memory-v2', output=Path(directory), codex='codex',
                                   external_skills=[], model=None, timeout=5)
            commands = []
            def fake_process(command, workspace, prompt, stdout, stderr, timeout):
                commands.append(command)
                events = [{'type':'thread.started','thread_id':str(len(commands))},
                          {'type':'turn.completed','usage':{}}]
                stdout.write_text('\n'.join(json.dumps(e) for e in events))
                stderr.write_text('')
                return {'exit_code':0,'timed_out':False,'seconds':0}
            with patch.object(eval_tool, 'run_process', side_effect=fake_process):
                result = eval_tool.run_case(args, Path(__file__).resolve().parents[1], 'candidate', 'R03', 1)
            self.assertEqual(len(commands), 2)
            self.assertTrue(all('resume' not in command and '--ephemeral' in command for command in commands))
            self.assertEqual(result['execution'], 'completed')
            self.assertEqual(result['contract_probe']['status'], 'fail')

    def test_freeze_includes_all_assets_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            asset = source / 'skills/aitasks-maintenance/assets/todo.md'
            asset.parent.mkdir(parents=True)
            asset.write_text('complete unchanged resource')
            (source/'.gitignore').write_text('todo.md\n')
            destination = root / 'frozen'
            eval_tool.freeze_source(source, destination)
            self.assertEqual((destination/'skills/aitasks-maintenance/assets/todo.md').read_bytes(), asset.read_bytes())
            self.assertIn('aitasks-maintenance/assets/todo.md', json.loads((destination/'manifest.json').read_text())['skills'])
            with self.assertRaises(FileExistsError):
                eval_tool.freeze_source(source, destination)
            with self.assertRaises(ValueError):
                eval_tool.validate_memory_package(destination)

    def test_external_skill_disables_use_files_not_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / 'sample/SKILL.md'
            skill.parent.mkdir()
            skill.write_text('sample')
            paths = eval_tool.discover_external_skills([root])
            self.assertEqual(paths, [skill.absolute()])
            args = SimpleNamespace(codex='codex', external_skills=paths, model=None)
            command = eval_tool.command_for(args, root, root / 'last.txt', 'R01')
            self.assertIn('skills.config=[{path=' + json.dumps(str(skill)) + ',enabled=false}]', command)

    def test_memory_suite_separates_task_contract_from_retrieval(self):
        for scenario in ('R01', 'R02'):
            files = eval_tool.fixture(scenario, 'memory-v1')
            self.assertGreater(files['.aitasks/lessons.md'].count('aitasks:lesson'), 30)
            self.assertIsNone(eval_tool.MEMORY_SCENARIOS[scenario][1])
        self.assertTrue(eval_tool.is_readonly('R02'))
        self.assertNotIn('context --query', eval_tool.fixture_rules(None, 'memory-v1'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'config.py').write_text(eval_tool.memory_fixture('R01')['config.py'])
            self.assertEqual(eval_tool.functional_check('R01', root)['status'], 'fail')
            (root/'config.py').write_text('def configure(options): return {"timeout": options.get("timeout",30)}\n')
            self.assertEqual(eval_tool.functional_check('R01', root)['status'], 'pass')

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
                               '# full skill\ncontent', 'code-review', ['/outside/skills'],
                               workspace=Path('/tmp/test-workspace'))

    def test_path_or_keyword_does_not_prove_skill_read_or_semantics(self):
        result = self.score('cat .agents/skills/code-review/SKILL.md', '# full skill')
        self.assertFalse(result['target_skill_read_proven'])
        self.assertEqual(result['manual_review']['status'], 'pending')
        self.assertEqual(result['acceptance'], 'unverified')

    def test_complete_read_is_proven_but_semantics_still_pending(self):
        path = Path('/tmp/test-workspace').resolve() / '.agents/skills/code-review/SKILL.md'
        result = self.score(f'cat {path}', '# full skill\ncontent')
        self.assertTrue(result['target_skill_read_proven'])
        self.assertEqual(result['acceptance'], 'unverified')

    def test_failed_read_does_not_count(self):
        path = Path('/tmp/test-workspace').resolve() / '.agents/skills/code-review/SKILL.md'
        result = self.score(f'cat {path}', '# full skill\ncontent', 1)
        self.assertFalse(result['target_skill_read_proven'])

    def test_readonly_ignored_write_fails(self):
        result = self.score('cat .agents/skills/code-review/SKILL.md', '# full skill\ncontent',
                            after={'.aitasks/todo.md': {'sha256': 'new'}})
        self.assertEqual(result['readonly_boundary'], 'fail')
        self.assertEqual(result['acceptance'], 'fail')

    def test_external_skill_read_is_reported(self):
        result = self.score('cat /outside/skills/another/SKILL.md', 'text')
        self.assertEqual(len(result['external_skill_reads_observed']), 1)

    def test_same_content_external_copy_does_not_prove_local_read(self):
        result = self.score('cat /outside/skills/code-review/SKILL.md', '# full skill\ncontent')
        self.assertFalse(result['target_skill_read_proven'])
        self.assertEqual(len(result['external_skill_reads_observed']), 1)

    def test_compound_command_does_not_prove_local_read(self):
        result = self.score('cat .agents/skills/code-review/SKILL.md && cat /outside/skills/code-review/SKILL.md',
                            '# full skill\ncontent')
        self.assertFalse(result['target_skill_read_proven'])

    def test_only_absolute_simple_reads_are_proven_without_command_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            expected = root/'.agents/skills/code-review/SKILL.md'
            expected.parent.mkdir(parents=True)
            expected.write_text('# full skill\ncontent')
            for command in (f'cat {expected}', f"bash -lc 'cat {expected}'"):
                with self.subTest(command=command):
                    trace = [{'command': command, 'aggregated_output': '# full skill\ncontent', 'exit_code': 0}]
                    self.assertTrue(eval_tool.local_skill_read_proven(trace, root, 'code-review', '# full skill\ncontent'))
            for command in ('cat .agents/skills/code-review/SKILL.md',
                            "bash -lc 'cat .agents/skills/code-review/SKILL.md'"):
                with self.subTest(command=command):
                    trace = [{'command': command, 'aggregated_output': '# full skill\ncontent', 'exit_code': 0}]
                    self.assertFalse(eval_tool.local_skill_read_proven(trace, root, 'code-review', '# full skill\ncontent'))
            outside = root/'outside.md'
            expected.unlink()
            outside.write_text('# full skill\ncontent')
            expected.symlink_to(outside)
            trace = [{'command': f'cat {expected}', 'aggregated_output': '# full skill\ncontent', 'exit_code': 0}]
            self.assertFalse(eval_tool.local_skill_read_proven(trace, root, 'code-review', '# full skill\ncontent'))

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

    def test_report_includes_instance_with_missing_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            eval_tool.prepare_output(output, 'review-v2')
            instance = output/'13-datetime-only'/'baseline-1'
            instance.mkdir(parents=True)
            (instance/'predeclared.json').write_text('{"scenario":"13","suite":"review-v2"}')
            (instance/'trace-1.jsonl').write_text('partial evidence\n')
            result = eval_tool.report(output)
            self.assertEqual(result['suite'], 'review-v2')
            self.assertEqual(result['scenario_runs'], 1)
            self.assertEqual(result['runs'][0]['execution'], 'incomplete')
            self.assertEqual(result['execution_completed'], 0)

    def test_report_distinguishes_runner_error_from_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            eval_tool.prepare_output(output, 'review-v2')
            instance = output/'13-datetime-only'/'candidate-1'
            instance.mkdir(parents=True)
            (instance/'runner-error.json').write_text('{"error_type":"OSError","message":"failure"}')
            result = eval_tool.report(output)
            self.assertEqual(result['runs'][0]['execution'], 'runner_error')
            self.assertEqual(result['runs'][0]['runner_error']['message'], 'failure')

    def test_report_counts_complete_and_interrupted_runs_together(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            eval_tool.prepare_output(output, 'review-v2')
            complete = output/'13-datetime-only'/'baseline-1'
            interrupted = output/'13-datetime-only'/'candidate-1'
            complete.mkdir(parents=True)
            interrupted.mkdir(parents=True)
            (complete/'result.json').write_text(json.dumps({
                'scenario': '13', 'suite': 'review-v2', 'variant': 'baseline', 'repetition': 1,
                'execution': 'completed', 'target_skill_read_proven': False,
                'readonly_boundary': 'pass', 'contract_probe': {'status': 'not_applicable'},
                'command_count': 1,
            }))
            (interrupted/'predeclared.json').write_text('{"scenario":"13","suite":"review-v2"}')
            result = eval_tool.report(output)
            self.assertEqual(result['scenario_runs'], 2)
            self.assertEqual(result['execution_completed'], 1)
            self.assertEqual(result['execution_incomplete'], 1)

    def test_runner_exception_is_recorded_without_overwriting_existing_run(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(suite='review-v2', output=Path(directory))
            eval_tool.prepare_output(args.output, args.suite)
            with patch.object(eval_tool, 'isolated_workspace', side_effect=OSError('fixture failed')):
                with self.assertRaises(OSError):
                    eval_tool.run_case(args, Path('/source'), 'baseline', '13', 1)
            instance = args.output/'13-datetime-only'/'baseline-1'
            error = json.loads((instance/'runner-error.json').read_text())
            self.assertEqual(error['error_type'], 'OSError')
            self.assertEqual(eval_tool.report(args.output)['runs'][0]['execution'], 'runner_error')
            with self.assertRaises(FileExistsError):
                eval_tool.run_case(args, Path('/source'), 'baseline', '13', 1)
            self.assertEqual(json.loads((instance/'runner-error.json').read_text()), error)

    def test_missing_followup_thread_fails_execution_and_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source'
            skill = source/'skills/ai-engineering-collaboration/SKILL.md'
            skill.parent.mkdir(parents=True)
            skill.write_text('# test skill\n')
            output = root/'out'
            output.mkdir()
            workspace = root/'workspace'
            workspace.mkdir()
            args = SimpleNamespace(suite='legacy', output=output, codex='unused',
                                   external_skills=[], model=None, timeout=5)
            def completed_without_thread(command, cwd, prompt, trace_path, stderr_path, timeout):
                trace_path.write_text(json.dumps({'type': 'turn.completed', 'usage': {}}) + '\n')
                stderr_path.write_text('')
                return {'exit_code': 0, 'timed_out': False}
            with patch.object(eval_tool, 'isolated_workspace', return_value=workspace), \
                 patch.object(eval_tool, 'run_process', side_effect=completed_without_thread):
                result = eval_tool.run_case(args, source, 'baseline', '04', 1)
            self.assertEqual(len(result['runs']), 1)
            self.assertEqual(result['execution'], 'fail')
            self.assertEqual(result['acceptance'], 'fail')

    def test_frontend_suite_natural_and_routed_fixtures(self):
        listed = subprocess.run([sys.executable, '-B', str(Path(eval_tool.__file__)),
                                 'list', '--suite', 'frontend-ui-v1'], capture_output=True, text=True)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(list(json.loads(listed.stdout)), ['F01', 'F02', 'F03', 'F04', 'F05', 'F06', 'F07', 'F08'])
        for scenario in ('F01', 'F02', 'F03', 'F04'):
            self.assertIsNone(eval_tool.SUITES['frontend-ui-v1'][scenario][1])
            rules = eval_tool.fixture_rules(None, 'frontend-ui-v1')
            self.assertNotIn('frontend-ui-ux', rules)
            self.assertNotIn('ai-engineering-collaboration', rules)
        for scenario in ('F05', 'F06', 'F07', 'F08'):
            routed = eval_tool.SUITES['frontend-ui-v1'][scenario][1]
            self.assertEqual(routed, 'ai-engineering-collaboration')
            self.assertIn(routed, eval_tool.fixture_rules(routed, 'frontend-ui-v1'))
        self.assertTrue(eval_tool.is_readonly('F04'))
        self.assertTrue(eval_tool.is_readonly('F08'))
        self.assertEqual(eval_tool.fixture('F01', 'frontend-ui-v1'), eval_tool.experience_fixture('X01'))
        self.assertEqual(eval_tool.fixture('F03', 'frontend-ui-v1'), eval_tool.experience_fixture('X02'))
        gap = eval_tool.fixture('F06', 'frontend-ui-v1')
        specified = eval_tool.fixture('F07', 'frontend-ui-v1')
        self.assertIn('确定布局', gap['PLAN.md'])
        self.assertIn('仅将 value=filter 的按钮文案', specified['PLAN.md'])

    def test_frontend_new_page_checks_only_supplied_activity_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in eval_tool.fixture('F02', 'frontend-ui-v1').items():
                destination = root/name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding='utf-8')
            missing = eval_tool.functional_check('F02', root)
            self.assertEqual(missing['status'], 'fail')
            page = root/'index.html'
            page.write_text('<html><body>绘本故事会 周六 10:00 二楼 '
                            '亲子手工坊 周日 14:00 一楼</body></html>', encoding='utf-8')
            bounded = eval_tool.functional_check('F02', root)
            self.assertEqual(bounded['status'], 'pass')
            self.assertIn('manual review', bounded['coverage'])
            page.write_text(page.read_text(encoding='utf-8').replace('亲子手工坊', ''), encoding='utf-8')
            self.assertEqual(eval_tool.functional_check('F02', root)['status'], 'unverified')

    def test_frontend_readonly_boundary_includes_ignored_files(self):
        trace = {'commands': [], 'errors': [], 'completed_turns': 1}
        for scenario in ('F04', 'F08'):
            entry = eval_tool.SUITES['frontend-ui-v1'][scenario][1]
            result = eval_tool.score(scenario, {'.aitasks/todo.md': {'sha256': 'before'}},
                                     {'.aitasks/todo.md': {'sha256': 'after'}}, [trace],
                                     [{'exit_code': 0}], '', entry, suite='frontend-ui-v1')
            self.assertEqual(result['readonly_boundary'], 'fail')
            self.assertEqual(result['acceptance'], 'fail')

    def test_frontend_suite_runs_old_baseline_without_new_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source'
            old_skill = source/'skills/code-review/SKILL.md'
            old_skill.parent.mkdir(parents=True)
            old_skill.write_text('# old baseline skill\n', encoding='utf-8')
            output = root/'output'
            output.mkdir()
            workspace = root/'workspace'
            workspace.mkdir()
            args = SimpleNamespace(suite='frontend-ui-v1', output=output, codex='unused',
                                   external_skills=[], model=None, timeout=5)
            def mock_process(command, cwd, prompt, trace_path, stderr_path, timeout):
                (cwd/'index.html').write_text('绘本故事会 周六 10:00 二楼 亲子手工坊 周日 14:00 一楼',
                                               encoding='utf-8')
                trace_path.write_text(json.dumps({'type': 'turn.completed', 'usage': {}}) + '\n')
                stderr_path.write_text('')
                return {'exit_code': 0, 'timed_out': False}
            with patch.object(eval_tool, 'isolated_workspace', return_value=workspace), \
                 patch.object(eval_tool, 'run_process', side_effect=mock_process):
                result = eval_tool.run_case(args, source, 'baseline', 'F02', 1)
            self.assertEqual(result['contract_probe']['status'], 'pass')
            self.assertEqual(result['acceptance'], 'unverified')
            self.assertIsNone(result['target_skill_read_proven'])
            self.assertFalse((workspace/'.agents/skills/frontend-ui-ux').exists())
            self.assertFalse((workspace/'predeclared.json').exists())

    def test_experience_suite_fixtures_and_bounded_contract_probes(self):
        self.assertEqual(list(eval_tool.SUITES['experience-v1']), ['X01', 'X02', 'X03'])
        self.assertIn('plan-execution', eval_tool.fixture_rules('plan-execution', 'experience-v1'))
        listed = subprocess.run([sys.executable, '-B', str(Path(eval_tool.__file__)),
                                 'list', '--suite', 'experience-v1'], capture_output=True, text=True)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(list(json.loads(listed.stdout)), ['X01', 'X02', 'X03'])
        for scenario, expected in [('X01', 'pass'), ('X02', 'fail'), ('X03', 'pass')]:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                files = eval_tool.fixture(scenario, 'experience-v1')
                for name, content in files.items():
                    destination = root/name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(content)
                result = eval_tool.functional_check(scenario, root)
                if scenario == 'X01' and result['status'] == 'unverified':
                    self.assertIn('loopback unavailable', result['stderr'])
                    continue
                self.assertEqual(result['status'], expected, result)
                self.assertIn('manual review', result['coverage'])
                if scenario == 'X01':
                    page = root/'index.html'
                    page.write_text(page.read_text().replace('<label for="amount">金额</label>', ''))
                    self.assertEqual(eval_tool.functional_check(scenario, root)['status'], 'fail')

                elif scenario == 'X02':
                    (root/'refund.py').write_text('def refund(ledger, request_id, amount):\n'
                        '    for item in ledger:\n'
                        '        if item["id"] == request_id: return item.copy()\n'
                        '    item = {"id": request_id, "amount": amount, "status": "ok"}\n'
                        '    ledger.append(item)\n'
                        '    return item.copy()\n')
                    self.assertEqual(eval_tool.functional_check(scenario, root)['status'], 'pass')
                else:
                    cli = root/'cli.py'
                    cli.write_text(cli.read_text().replace('"CONNECT_FAILED"', '"OTHER_ERROR"'))
                    self.assertEqual(eval_tool.functional_check(scenario, root)['status'], 'fail')

    def test_ui_probe_resolves_button_form_ownership_and_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in eval_tool.fixture('X01', 'experience-v1').items():
                destination = root/name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding='utf-8')

            def page(amount_form, submit, extra=''):
                return ('<!doctype html><p role="alert">失败</p><p role="status">{{STATUS}}</p>'
                        + submit + amount_form + extra
                        + '<form action="/action" method="post"><button name="action" value="retry">重试</button></form>')

            base_form = ('<form id="amount-form" action="/action" method="post">'
                         '<label for="amount">金额</label><input id="amount" name="amount">'
                         '<button name="action" value="filter">筛选</button>{inside}</form>')
            outer = '<button form="amount-form" name="action" value="submit">提交</button>'
            nested = '<button name="action" value="submit">提交</button>'
            cases = {
                'external forward reference': (page(base_form.format(inside=''), outer), True),
                'nested default submit': (page(base_form.format(inside=nested), ''), True),
                'valid button overrides': (page(base_form.replace('action="/action" method="post"',
                    'action="/wrong" method="get"').replace('value="filter"',
                    'value="filter" formaction="/action" formmethod="post"').format(inside=''),
                    outer.replace('value="submit"', 'value="submit" formaction="/action" formmethod="post"')), True),
                'missing form id': (page(base_form.format(inside=''), outer.replace('amount-form', 'missing')), False),
                'empty form id': (page(base_form.format(inside=''), outer.replace('amount-form', '')), False),
                'wrong associated form': (page(base_form.format(inside=''), outer.replace('amount-form', 'other'),
                    '<form id="other" action="/wrong" method="post"></form>'), False),
                'wrong associated method': (page(base_form.format(inside=''), outer.replace('amount-form', 'other'),
                    '<form id="other" action="/action" method="get"></form>'), False),
                'id belongs to non-form element': (page(base_form.format(inside=''), outer.replace('amount-form', 'other'),
                    '<div id="other"></div>'), False),
                'nested form attribute overrides ancestor': (page(base_form.format(inside=nested.replace(
                    'value="submit"', 'value="submit" form="missing"')), ''), False),
                'nested button linked to other valid form': (page(base_form.format(inside=nested.replace(
                    'value="submit"', 'value="submit" form="other"')), '',
                    '<form id="other" action="/action" method="post"><label for="other-amount">金额</label>'
                    '<input id="other-amount" name="amount"></form>'), True),
                'nested button linked to other invalid form': (page(base_form.format(inside=nested.replace(
                    'value="submit"', 'value="submit" form="other"')), '',
                    '<form id="other" action="/wrong" method="post"></form>'), False),
                'wrong form action override': (page(base_form.format(inside=''), outer.replace(
                    'value="submit"', 'value="submit" formaction="/wrong"')), False),
                'wrong form method override': (page(base_form.format(inside=''), outer.replace(
                    'value="submit"', 'value="submit" formmethod="get"')), False),
                'non-submit button': (page(base_form.format(inside=''), outer.replace(
                    'value="submit"', 'value="submit" type="button"')), False),
                'disabled button': (page(base_form.format(inside=''), outer.replace(
                    'value="submit"', 'value="submit" disabled')), False),
            }
            for name, (html, valid) in cases.items():
                with self.subTest(case=name):
                    (root/'index.html').write_text(html, encoding='utf-8')
                    result = eval_tool.functional_check('X01', root)
                    if valid:
                        self.assertIn(result['status'], ('pass', 'unverified'), result)
                        if result['status'] == 'unverified':
                            self.assertIn('loopback unavailable', result['stderr'])
                    else:
                        self.assertEqual(result['status'], 'fail', result)

    def test_ui_probe_checks_amount_input_owner_and_usability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in eval_tool.fixture('X01', 'experience-v1').items():
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            original = (root/'index.html').read_text(encoding='utf-8')
            original_form = '<form action="/action" method="post"><label for="amount">金额</label>'
            named_form = '<form id="amount-form" action="/action" method="post"><label for="amount">金额</label>'
            named = original.replace(original_form, named_form)
            input_html = '<input id="amount" name="amount" type="number" min="1" required>'
            filter_html = '<button name="action" value="filter">处理</button>'
            cases = {
                'nested amount': (named, True),
                'external amount with forward form reference': (named.replace(input_html, '').replace(
                    named_form, input_html.replace(' name="amount"', ' form="amount-form" name="amount"')
                    + named_form), True),
                'input overrides ancestor with valid form': (named.replace(input_html,
                    input_html.replace(' name="amount"', ' form="amount-form" name="amount"')), True),
                'disabled amount': (named.replace(input_html, input_html.replace(' required>', ' required disabled>')), False),
                'disabled fieldset disables input': (named.replace(input_html,
                    '<fieldset disabled>' + input_html + '</fieldset>'), False),
                'first legend exempts input': (named.replace(input_html,
                    '<fieldset disabled><legend>' + input_html + '</legend></fieldset>'), True),
                'second legend does not exempt input': (named.replace(input_html,
                    '<fieldset disabled><legend>说明</legend><legend>' + input_html + '</legend></fieldset>'), False),
                'disabled inner fieldset still applies': (named.replace(input_html,
                    '<fieldset disabled><legend><fieldset disabled>' + input_html
                    + '</fieldset></legend></fieldset>'), False),
                'disabled fieldset disables button': (named.replace(filter_html,
                    '<fieldset disabled>' + filter_html + '</fieldset>'), False),
                'first legend exempts button': (named.replace(filter_html,
                    '<fieldset disabled><legend>' + filter_html + '</legend></fieldset>'), True),
                'missing owner overrides ancestor': (named.replace(input_html,
                    input_html.replace(' name="amount"', ' form="missing" name="amount"')), False),
                'empty owner overrides ancestor': (named.replace(input_html,
                    input_html.replace(' name="amount"', ' form="" name="amount"')), False),
                'external input without owner': (named.replace(input_html, '').replace(named_form,
                    input_html + named_form), False),
                'input points to wrong form': (named.replace(input_html,
                    input_html.replace(' name="amount"', ' form="other" name="amount"')).replace(
                    '</body>', '<form id="other" action="/action" method="post"></form></body>'), False),
                'submit has no amount': (named.replace('value="submit"', 'value="submit" form="other"').replace(
                    '</body>', '<form id="other" action="/action" method="post"></form></body>'), False),
                'filter has no amount': (named.replace('value="filter"', 'value="filter" form="other"').replace(
                    '</body>', '<form id="other" action="/action" method="post"></form></body>'), False),
            }
            for name, (html, valid) in cases.items():
                with self.subTest(case=name):
                    (root/'index.html').write_text(html, encoding='utf-8')
                    result = eval_tool.functional_check('F01', root)
                    if valid:
                        self.assertIn(result['status'], ('pass', 'unverified'), result)
                    else:
                        self.assertEqual(result['status'], 'fail', result)

    def test_ui_probe_accepts_roles_emitted_only_in_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in eval_tool.fixture('X01', 'experience-v1').items():
                destination = root/name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding='utf-8')
            page = root/'index.html'
            page.write_text(page.read_text(encoding='utf-8')
                            .replace('<p role="alert">退款失败时可以重试。</p>', '')
                            .replace('<p role="status">{{STATUS}}</p>', '{{STATUS}}'), encoding='utf-8')
            app = root/'app.py'
            app.write_text(app.read_text(encoding='utf-8').replace(
                'self.wfile.write(page.replace("{{STATUS}}", escape(message)).encode())',
                'role = "alert" if message == "退款失败" else "status"\n'
                '        feedback = (\'<p role="\' + role + \'">\' + escape(message) + \'</p>\') if message else ""\n'
                '        self.wfile.write(page.replace("{{STATUS}}", feedback).encode())'), encoding='utf-8')
            result = eval_tool.functional_check('X01', root)
            self.assertIn(result['status'], ('pass', 'unverified'), result)
            if result['status'] == 'unverified':
                self.assertIn('loopback unavailable', result['stderr'])
                return
            app.write_text(app.read_text(encoding='utf-8').replace(
                'role = "alert" if message == "退款失败" else "status"',
                'role = "presentation" if message == "退款失败" else "status"'), encoding='utf-8')
            self.assertEqual(eval_tool.functional_check('X01', root)['status'], 'fail')

    def test_loopback_fixture_starts_without_reverse_dns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in eval_tool.fixture('X01', 'experience-v1').items():
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            result = subprocess.run([sys.executable, '-B', '-c', '''import app
import socket
def unavailable(*args):
    raise RuntimeError("reverse DNS unavailable")
socket.getfqdn = unavailable
server = app.LoopbackHTTPServer(("127.0.0.1", 0), app.Handler)
try:
    assert server.server_name == "localhost" and server.server_port > 0
finally:
    server.server_close()
'''], cwd=root, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_experience_runner_keeps_scoring_outside_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source'
            skill = source/'skills/plan-execution/SKILL.md'
            skill.parent.mkdir(parents=True)
            skill.write_text('# test skill\n')
            output = root/'output'
            output.mkdir()
            workspace = root/'workspace'
            workspace.mkdir()
            args = SimpleNamespace(suite='experience-v1', output=output, codex='unused',
                                   external_skills=[], model=None, timeout=5)
            def completed(command, cwd, prompt, trace_path, stderr_path, timeout):
                trace_path.write_text(json.dumps({'type': 'turn.completed', 'usage': {}}) + '\n')
                stderr_path.write_text('')
                return {'exit_code': 0, 'timed_out': False}
            with patch.object(eval_tool, 'isolated_workspace', return_value=workspace), \
                 patch.object(eval_tool, 'run_process', side_effect=completed):
                result = eval_tool.run_case(args, source, 'baseline', 'X03', 1)
            self.assertEqual(result['contract_probe']['status'], 'pass')
            self.assertEqual(result['acceptance'], 'unverified')
            self.assertFalse((workspace/'predeclared.json').exists())
            self.assertIn('plan-execution', (workspace/'AGENTS.md').read_text())
            self.assertNotIn('精简人类可读信息', (workspace/'AGENTS.md').read_text())

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


class BatchEvaluationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root/'source'
        skill = self.source/'skills/code-review/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('Original standalone skill\n')
        (self.source/'VERSION').write_text('1.0\n')
        self.args = SimpleNamespace(output=self.root/'out', suite='selection-v1',
            baseline=self.source, candidate=self.source, codex='fake-codex', model='test-model',
            timeout=5, external_skills=[], jobs=1, include_no_skill=False)
        self.cli = patch.object(eval_tool, 'cli_identity', create=True,
            return_value={'path': '/test/codex', 'sha256': 'cli-v1'})
        self.cli.start()
        self.addCleanup(self.cli.stop)

    def test_batch_freezes_full_sources_and_rejects_changed_conditions(self):
        first = eval_tool.prepare_batch(self.args)
        marker = (self.args.output/'batch.json').read_bytes()
        frozen = self.args.output/'.sources/candidate/skills/code-review/SKILL.md'
        self.assertEqual(frozen.read_text(), 'Original standalone skill\n')
        self.assertEqual(eval_tool.prepare_batch(self.args)['batch_id'], first['batch_id'])
        for field, value in [('model', 'other'), ('timeout', 6), ('jobs', 2),
                             ('include_no_skill', True), ('external_skills', [Path('/disabled/SKILL.md')])]:
            changed = copy.copy(self.args)
            setattr(changed, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                eval_tool.prepare_batch(changed)
            self.assertEqual((self.args.output/'batch.json').read_bytes(), marker)
        (self.source/'skills/code-review/SKILL.md').write_text('Changed source\n')
        self.assertEqual(frozen.read_text(), 'Original standalone skill\n')
        eval_tool.verify_batch_sources(self.args.output, first)
        with self.assertRaises(ValueError):
            eval_tool.prepare_batch(self.args)
        self.assertEqual((self.args.output/'batch.json').read_bytes(), marker)

    def test_each_cli_call_rejects_drift_and_retains_the_observed_run(self):
        batch = eval_tool.prepare_batch(self.args)
        self.args.batch = batch
        for field in ('cli', 'runtime', 'runner_files'):
            with self.subTest(field=field):
                output = self.args.output / field
                output.mkdir()
                args = copy.copy(self.args)
                args.output = output
                shutil.copytree(self.args.output / '.sources', output / '.sources')
                identity = {'cli': batch['identity']['cli'], 'runtime': batch['identity']['runtime'],
                            'runner_files': batch['identity']['runner_files']}
                calls = []
                def completed(command, workspace, prompt, stdout, stderr, timeout):
                    calls.append(command)
                    stdout.write_text(json.dumps({'type': 'turn.completed', 'usage': {}})+'\n')
                    stderr.write_text('')
                    identity[field] = {'changed': True}
                    return {'exit_code': 0, 'timed_out': False, 'seconds': 1}
                with patch.object(eval_tool, 'cli_identity', side_effect=lambda _: identity['cli']), \
                     patch.object(eval_tool, 'runtime_identity', side_effect=lambda: identity['runtime']), \
                     patch.object(eval_tool, 'runner_files', side_effect=lambda: identity['runner_files']), \
                     patch.object(eval_tool, 'run_process', side_effect=completed):
                    with self.assertRaisesRegex(ValueError, 'execution conditions changed'):
                        eval_tool.run_case(args, output/'.sources/baseline', 'baseline', 'S01', 1)
                    instance = output/'S01-explain/baseline-1'
                    self.assertTrue((instance/'trace-1.jsonl').is_file())
                    self.assertTrue((instance/'workspace/labels.py').is_file())
                    self.assertTrue((instance/'execution-before-1.json').is_file())
                    self.assertTrue((instance/'execution-after-1.json').is_file())
                    self.assertTrue((instance/'runner-error.json').is_file())
                    self.assertFalse((instance/'result.json').exists())
                    with self.assertRaisesRegex(ValueError, 'execution conditions changed'):
                        eval_tool.run_case(args, output/'.sources/candidate', 'candidate', 'S01', 1)
                    self.assertEqual(len(calls), 1)

    def test_batch_rejects_runner_cli_and_frozen_source_drift(self):
        batch = eval_tool.prepare_batch(self.args)
        with patch.object(eval_tool, 'runner_identity', return_value='changed-runner'):
            with self.assertRaises(ValueError):
                eval_tool.prepare_batch(self.args)
        with patch.object(eval_tool, 'cli_identity', return_value={'path': '/test/codex', 'sha256': 'cli-v2'}):
            with self.assertRaises(ValueError):
                eval_tool.prepare_batch(self.args)
        with patch.object(eval_tool, 'runner_files', return_value={'observation_eval.py': 'changed-helper'}):
            with self.assertRaises(ValueError):
                eval_tool.prepare_batch(self.args)
        with patch.object(eval_tool, 'runtime_identity', return_value={'environment_sha256': 'changed-runtime'}):
            with self.assertRaises(ValueError):
                eval_tool.prepare_batch(self.args)
        (self.args.output/'.sources/baseline/skills/code-review/SKILL.md').write_text('Tampered\n')
        with self.assertRaises(ValueError):
            eval_tool.verify_batch_sources(self.args.output, batch)
        with self.assertRaises(ValueError):
            eval_tool.prepare_batch(self.args)

    def test_legacy_output_can_report_but_cannot_be_promoted_to_locked_batch(self):
        eval_tool.prepare_output(self.args.output, 'selection-v1')
        marker = (self.args.output/'suite.json').read_bytes()
        self.assertEqual(eval_tool.report(self.args.output)['batch']['status'], 'legacy_unlocked')
        with self.assertRaises(ValueError):
            eval_tool.prepare_batch(self.args)
        self.assertEqual((self.args.output/'suite.json').read_bytes(), marker)
        self.assertFalse((self.args.output/'batch.json').exists())

    def test_source_links_and_drift_during_freeze_fail_before_batch_is_locked(self):
        link = self.source/'skills/code-review/outside'
        link.symlink_to(self.root/'outside')
        with self.assertRaises(ValueError):
            eval_tool.prepare_batch(self.args)
        link.unlink()
        original = eval_tool.freeze_source
        def changing(source, destination):
            original(source, destination)
            (self.source/'skills/code-review/SKILL.md').write_text('Changed during freeze\n')
        with patch.object(eval_tool, 'freeze_source', side_effect=changing):
            with self.assertRaises(ValueError):
                eval_tool.prepare_batch(self.args)
        self.assertFalse((self.args.output/'batch.json').exists())

    def result(self, batch, scenario, variant, *, efficiency='pass', correctness='pass', batch_id=None):
        name = eval_tool.SUITES['selection-v1'][scenario][0]
        instance = self.args.output/f'{scenario}-{name}'/f'{variant}-1'
        instance.mkdir(parents=True)
        result = {'suite': 'selection-v1', 'scenario': scenario, 'variant': variant, 'repetition': 1,
            'batch_id': batch_id or batch['batch_id'],
            'dataset_split': 'holdout' if scenario in eval_tool.SELECTION_HOLDOUT else 'development',
            'execution': 'completed', 'acceptance': 'unverified', 'target_skill_read_proven': None,
            'readonly_boundary': 'pass', 'contract_probe': {'status': 'not_applicable'}, 'command_count': 3,
            'runs': [{'seconds': 2}], 'trace_summary': [{'usage': [{'input_tokens': 10, 'output_tokens': 4}]}]}
        (instance/'result.json').write_text(json.dumps(result))
        (instance/'trace-1.jsonl').write_text('evidence\n')
        declaration = {'batch_id': batch['batch_id'], 'batch_identity_sha256': batch['identity_sha256'],
            'source_skills': batch['identity']['sources'][variant]['skills'],
            'model': self.args.model, 'timeout': self.args.timeout,
            'policy': batch['identity']['policy'], 'external_skill_disables': []}
        (instance/'predeclared.json').write_text(json.dumps(declaration))
        identity = {key: batch['identity'][key] for key in ('runner_files', 'cli', 'runtime')}
        for boundary in ('before', 'after'):
            (instance/f'execution-{boundary}-1.json').write_text(json.dumps(identity))
        review = {'schema_version': 1, 'reviewer': {'kind': 'agent', 'id': 'test'},
            'dimensions': {name: {'status': 'pass', 'reason': 'Observed',
                'evidence': [{'path': 'trace-1.jsonl', 'line': 1}]} for name in eval_tool.REVIEW_DIMENSIONS}}
        review['dimensions']['process_efficiency']['status'] = efficiency
        review['dimensions']['task_correctness']['status'] = correctness
        (instance/'review.json').write_text(json.dumps(review))
        return instance

    def test_cost_provenance_requires_archived_execution_boundaries_not_current_runtime(self):
        batch = eval_tool.prepare_batch(self.args)
        for variant in ('baseline', 'candidate'):
            self.result(batch, 'S01', variant)
        with patch.object(eval_tool, 'runtime_identity', side_effect=AssertionError('must not inspect current runtime')):
            self.assertEqual(eval_tool.report(self.args.output)['pairs'][0]['comparison']['status'], 'eligible')
        path = self.args.output/'S01-explain/candidate-1/execution-after-1.json'
        original = path.read_bytes()
        path.unlink()
        self.assertEqual(eval_tool.report(self.args.output)['pairs'][0]['comparison']['status'], 'ineligible')
        path.write_text('{}')
        self.assertEqual(eval_tool.report(self.args.output)['pairs'][0]['comparison']['status'], 'ineligible')
        path.write_bytes(original)
        self.assertEqual(eval_tool.report(self.args.output)['pairs'][0]['comparison']['status'], 'eligible')

    def test_pairs_keep_failed_and_uncreated_members_and_separate_splits(self):
        batch = eval_tool.prepare_batch(self.args)
        tasks = [(self.source, variant, scenario, 1) for scenario in ('S01', 'S07')
                 for variant in ('baseline', 'candidate')]
        eval_tool.register_batch_runs(self.args.output, batch, tasks)
        a = self.result(batch, 'S01', 'baseline', efficiency='fail')
        b = self.result(batch, 'S01', 'candidate')
        self.result(batch, 'S07', 'baseline', correctness='fail')
        originals = [(p, p.read_bytes()) for p in self.args.output.glob('*/*/result.json')]
        summary = eval_tool.report(self.args.output)
        self.assertEqual(summary['scenario_runs'], 4)
        self.assertEqual(summary['execution_not_created'], 1)
        self.assertEqual(summary['pairs'][0]['comparison']['status'], 'eligible')
        self.assertEqual(summary['pairs'][0]['comparison']['metrics']['baseline']['seconds'], 2)
        self.assertEqual(summary['pairs'][0]['comparison']['metrics']['candidate']['input_tokens'], 10)
        self.assertEqual(summary['pairs'][1]['comparison']['status'], 'ineligible')
        self.assertEqual(summary['pairs'][1]['members']['candidate']['execution'], 'not_created')
        self.assertEqual(summary['by_split']['development']['scenario_runs'], 2)
        self.assertEqual(summary['by_split']['holdout']['scenario_runs'], 2)
        for path, contents in originals:
            self.assertEqual(path.read_bytes(), contents)
        with self.assertRaises(ValueError):
            eval_tool.register_batch_runs(self.args.output, batch, [(self.source, 'baseline', 'S01', 1)])
        eval_tool.register_batch_runs(self.args.output, batch, [(self.source, 'baseline', 'S03', 1)])
        self.assertEqual(len(json.loads((self.args.output/'planned-runs.json').read_text())), 6)
        self.assertEqual(eval_tool.prepare_batch(self.args)['batch_id'], batch['batch_id'])

    def test_pair_costs_require_trusted_validity_and_batch_provenance(self):
        batch = eval_tool.prepare_batch(self.args)
        for variant in ('baseline', 'candidate'):
            self.result(batch, 'S01', variant, batch_id='foreign' if variant == 'candidate' else None)
        summary = eval_tool.report(self.args.output)
        self.assertTrue(all(p['comparison']['status'] == 'ineligible' for p in summary['pairs']))
        path = self.args.output/'S01-explain/candidate-1/result.json'
        data = json.loads(path.read_text()); data['batch_id'] = batch['batch_id']; path.write_text(json.dumps(data))
        review_path = path.parent/'review.json'
        review = json.loads(review_path.read_text())
        review['dimensions']['evaluation_validity']['status'] = 'unverified'
        review_path.write_text(json.dumps(review))
        summary = eval_tool.report(self.args.output)
        self.assertEqual(summary['pairs'][0]['comparison']['status'], 'ineligible')

    def test_early_runner_error_keeps_planned_split_and_pair_identity(self):
        batch = eval_tool.prepare_batch(self.args)
        eval_tool.register_batch_runs(self.args.output, batch, [(self.source, 'baseline', 'S07', 1)])
        self.result(batch, 'S07', 'baseline')
        failed = self.args.output/'S07-go-review/candidate-1'
        failed.mkdir(parents=True)
        (failed/'runner-error.json').write_text('{"error_type":"OSError","message":"before declaration"}')
        summary = eval_tool.report(self.args.output)
        self.assertEqual(len(summary['pairs']), 1)
        self.assertEqual(summary['pairs'][0]['dataset_split'], 'holdout')
        self.assertEqual(summary['pairs'][0]['members']['candidate']['execution'], 'runner_error')
        self.assertEqual(summary['by_split']['holdout']['scenario_runs'], 2)

    def test_no_skill_is_separate_control_and_missing_metric_is_not_zero(self):
        self.args.include_no_skill = True
        batch = eval_tool.prepare_batch(self.args)
        eval_tool.register_batch_runs(self.args.output, batch, [(self.source, 'baseline', 'S01', 1)])
        for variant in ('baseline', 'candidate'):
            p = self.result(batch, 'S01', variant)
            result = json.loads((p/'result.json').read_text())
            result['trace_summary'] = [{'usage': [{}]}]
            (p/'result.json').write_text(json.dumps(result))
        summary = eval_tool.report(self.args.output)
        pair = summary['pairs'][0]
        self.assertEqual(pair['comparison']['status'], 'eligible')
        self.assertEqual(pair['no_skill']['execution'], 'not_created')
        self.assertIsNone(pair['comparison']['metrics']['baseline']['input_tokens'])

    def test_main_runs_frozen_sources_even_when_original_changes_between_variants(self):
        seen = []
        def completed(command, workspace, prompt, stdout, stderr, timeout):
            seen.append((workspace/'.agents/skills/code-review/SKILL.md').read_text())
            (self.source/'skills/code-review/SKILL.md').write_text('Concurrent source edit\n')
            stdout.write_text(json.dumps({'type': 'turn.completed', 'usage': {}}) + '\n')
            stderr.write_text('')
            return {'exit_code': 0, 'timed_out': False, 'seconds': 1}
        argv = ['behavior_eval', 'run', '--suite', 'selection-v1', '--scenarios', 'S01',
                '--baseline', str(self.source), '--candidate', str(self.source),
                '--output', str(self.args.output), '--repetitions', '1', '--model', 'test-model']
        with patch.object(sys, 'argv', argv), patch.object(eval_tool, 'discover_external_skills', return_value=[]), \
             patch.object(eval_tool, 'run_process', side_effect=completed), redirect_stdout(io.StringIO()):
            eval_tool.main()
        self.assertEqual(seen, ['Original standalone skill\n', 'Original standalone skill\n'])
        summary = json.loads((self.args.output/'summary.json').read_text())
        self.assertEqual(summary['execution_completed'], 2)
        self.assertEqual(summary['batch']['status'], 'locked')
        self.assertEqual(summary['pairs'][0]['comparison']['status'], 'ineligible')


if __name__ == '__main__':
    unittest.main()
