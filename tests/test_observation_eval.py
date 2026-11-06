import importlib.util
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('observation_eval', Path(__file__).resolve().parents[1] / 'evals/observation_eval.py')
observation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observation)
RUNNER_SPEC = importlib.util.spec_from_file_location('observation_runner', Path(__file__).resolve().parents[1] / 'evals/behavior_eval.py')
runner = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(runner)


FIRST_KEY = hashlib.sha256(b"export.offset.strip-tzinfo").hexdigest()[:32]
SECOND_KEY = hashlib.sha256(b"export.offset.input-parser").hexdigest()[:32]

def snapshot(root):
    return {str(p.relative_to(root)): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'mode': p.stat().st_mode & 0o777}
            for p in root.rglob('*') if p.is_file()}


class ObservationEvaluationTests(unittest.TestCase):
    def source(self, root):
        for name in ['code-review', 'aitasks-maintenance']:
            path = root/'skills'/name/'SKILL.md'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'# {name}\n')
        return root

    def test_standalone_install_profile_is_preserved_in_locked_batch_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.source(root/'source')
            args = SimpleNamespace(suite='maintenance-v2', output=root/'out', codex=sys.executable,
                                   baseline=source, candidate=source, model='fixture-model', timeout=5,
                                   external_skills=[], jobs=1, include_no_skill=False)
            args.batch = runner.prepare_batch(args)
            def completed(command, cwd, prompt, trace_path, stderr_path, timeout):
                self.assertEqual({p.name for p in (cwd/'.agents/skills').iterdir()}, {'code-review'})
                self.assertIn('先读取 .agents/skills/code-review/SKILL.md', (cwd/'AGENTS.md').read_text())
                trace_path.write_text(json.dumps({'type': 'turn.completed', 'usage': {}})+'\n')
                stderr_path.write_text('')
                return {'exit_code': 0, 'timed_out': False}
            with patch.object(runner, 'run_process', side_effect=completed):
                result = runner.run_case(args, args.output/'.sources/baseline', 'baseline', 'M08', 1)
            self.assertEqual(result['readonly_boundary'], 'pass')
            instance = args.output/'M08-standalone-review/baseline-1'
            declaration = json.loads((instance/'predeclared.json').read_text())
            self.assertTrue(declaration['source_skills'])
            self.assertTrue(all(name.startswith('code-review/') for name in declaration['source_skills']))
            review = {'schema_version': 1, 'reviewer': {'kind': 'agent', 'id': 'unit-fixture'},
                      'dimensions': {name: {'status': 'pass', 'reason': 'fixture assertion',
                                           'evidence': [{'path': 'predeclared.json'}]} for name in runner.REVIEW_DIMENSIONS}}
            (instance/'review.json').write_text(json.dumps(review))
            with redirect_stdout(io.StringIO()):
                summary = runner.report(args.output)
            self.assertNotIn('baseline: instance provenance is not verified', summary['pairs'][0]['comparison']['reasons'])

    def test_observation_runner_uses_new_sessions_and_adds_only_second_task_code(self):
        for scenario in ['M06', 'M07']:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = self.source(root/'source')
                args = SimpleNamespace(suite='maintenance-v2', output=root/'out', codex='unused',
                                       external_skills=[], model=None, timeout=5)
                calls = []
                def completed(command, cwd, prompt, trace_path, stderr_path, timeout):
                    self.assertNotIn('resume', command)
                    self.assertIn('--ephemeral', command)
                    expected = observation.FIRST_SOURCE + (observation.SECOND_SOURCE[scenario] if calls else '')
                    self.assertEqual((cwd/'export.py').read_text(), expected)
                    calls.append(command)
                    trace_path.write_text(json.dumps({'type': 'thread.started', 'thread_id': str(len(calls))})+'\n'
                                          +json.dumps({'type': 'turn.completed', 'usage': {}})+'\n')
                    stderr_path.write_text('')
                    return {'exit_code': 0, 'timed_out': False}
                with patch.object(runner, 'run_process', side_effect=completed):
                    result = runner.run_case(args, source, 'candidate', scenario, 1)
                self.assertEqual(len(calls), 2)
                # No observation was written by the fixture executor: do not pass merely for two exits of zero.
                self.assertEqual(result['contract_probe']['memory_flow']['status'], 'fail')

    def prepare(self, root, scenario):
        workspace, first = root/'workspace', root/'first'
        for name, body in observation.fixture(scenario).items():
            path = workspace/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        before = snapshot(workspace)
        rows = {FIRST_KEY: {'key': 'export.offset.strip-tzinfo', 'tasks': ['task-a'],
                        'evidence': 'export.py:2', 'lesson_id': None}}
        (workspace/'.aitasks/.observations.json').write_text(json.dumps({'version': 1, 'observations': rows}))
        after_first = snapshot(workspace)
        first.mkdir()
        for name in ['lessons.md', 'todo.md', '.observations.json']:
            (first/name).write_bytes((workspace/'.aitasks'/name).read_bytes())
        observation.add_second_task(workspace, scenario)
        return workspace, first, before, after_first, rows

    def test_same_cause_observation_and_one_linked_lesson_pass_artifact_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace, first, before, after_first, rows = self.prepare(Path(tmp), 'M06')
            rows[FIRST_KEY].update(tasks=['task-a', 'task-b'], lesson_id='lesson-one')
            (workspace/'.aitasks/.observations.json').write_text(json.dumps({'version': 1, 'observations': rows}))
            (workspace/'.aitasks/lessons.md').write_text('<!-- aitasks:lesson id=lesson-one -->\n## 保留日期偏移\n- 原因：导出移除时区。\n')
            args = (workspace, first, [{'thread_id': 'first'}, {'thread_id': 'second'}], before, after_first, snapshot(workspace))
            self.assertEqual(observation.check_flow('M06', *args)['status'], 'pass')
            rows[FIRST_KEY]['tasks'] = ['task-a', 'task-a']
            (workspace/'.aitasks/.observations.json').write_text(json.dumps({'version': 1, 'observations': rows}))
            self.assertEqual(observation.check_flow('M06', *args)['status'], 'fail')

    def test_different_causes_require_two_single_observations_without_lesson(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace, first, before, after_first, rows = self.prepare(Path(tmp), 'M07')
            rows[SECOND_KEY] = {'key': 'export.offset.input-parser', 'tasks': ['task-b'],
                           'evidence': 'export.py:6', 'lesson_id': None}
            (workspace/'.aitasks/.observations.json').write_text(json.dumps({'version': 1, 'observations': rows}))
            args = (workspace, first, [{'thread_id': 'first'}, {'thread_id': 'second'}], before, after_first, snapshot(workspace))
            self.assertEqual(observation.check_flow('M07', *args)['status'], 'pass')
            rows.pop(SECOND_KEY)
            rows[FIRST_KEY]['tasks'].append('task-b')
            (workspace/'.aitasks/.observations.json').write_text(json.dumps({'version': 1, 'observations': rows}))
            self.assertEqual(observation.check_flow('M07', *args)['status'], 'fail')

    def test_first_task_may_observe_but_may_not_change_code_or_write_lesson(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace, first, before, after_first, rows = self.prepare(Path(tmp), 'M07')
            rows[SECOND_KEY] = {'key': 'export.offset.input-parser', 'tasks': ['task-b'], 'evidence': 'export.py:6', 'lesson_id': None}
            (workspace/'.aitasks/.observations.json').write_text(json.dumps({'version': 1, 'observations': rows}))
            traces = [{'thread_id': 'first'}, {'thread_id': 'second'}]
            changed = dict(after_first, **{'export.py': 'changed'})
            self.assertEqual(observation.check_flow('M07', workspace, first, traces, before, changed, snapshot(workspace))['status'], 'fail')
            (first/'lessons.md').write_text('<!-- aitasks:lesson id=too-early -->\n## Too early\n')
            self.assertEqual(observation.check_flow('M07', workspace, first, traces, before, after_first, snapshot(workspace))['status'], 'fail')

    def test_independent_session_proof_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace, first, before, after_first, rows = self.prepare(Path(tmp), 'M07')
            rows[SECOND_KEY] = {'key': 'export.offset.input-parser', 'tasks': ['task-b'], 'evidence': 'export.py:6', 'lesson_id': None}
            (workspace/'.aitasks/.observations.json').write_text(json.dumps({'version': 1, 'observations': rows}))
            for identities, status in [(('one', None), 'unverified'), (('one', 'one'), 'fail'), (('one', 'two'), 'pass')]:
                with self.subTest(identities=identities):
                    result = observation.check_flow('M07', workspace, first, [{'thread_id': x} for x in identities], before, after_first, snapshot(workspace))
                    self.assertEqual(result['status'], status)
                    self.assertEqual(result.get('required_evidence_unverified', False), status == 'unverified')

    def test_corrupt_state_or_unrelated_persistent_change_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace, first, before, after_first, rows = self.prepare(Path(tmp), 'M07')
            traces = [{'thread_id': 'first'}, {'thread_id': 'second'}]
            (workspace/'.aitasks/.observations.json').write_text('{bad')
            self.assertEqual(observation.check_flow('M07', workspace, first, traces, before, after_first, snapshot(workspace))['status'], 'fail')
            rows[SECOND_KEY] = {'key': 'export.offset.input-parser', 'tasks': ['task-b'], 'evidence': 'export.py:6', 'lesson_id': None}
            (workspace/'.aitasks/.observations.json').write_text(json.dumps({'version': 1, 'observations': rows}))
            (workspace/'unrelated.txt').write_text('unexpected')
            self.assertEqual(observation.check_flow('M07', workspace, first, traces, before, after_first, snapshot(workspace))['status'], 'fail')

    def test_invalid_signature_and_code_newline_change_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace, first, before, after_first, rows = self.prepare(Path(tmp), 'M07')
            rows[SECOND_KEY] = {'key': 'export.offset.input-parser', 'tasks': ['task-b'], 'evidence': 'export.py:6', 'lesson_id': None}
            traces = [{'thread_id': 'first'}, {'thread_id': 'second'}]
            state_file = workspace/'.aitasks/.observations.json'
            state_file.write_text(json.dumps({'version': 1, 'observations': dict(rows, bogus=rows[FIRST_KEY])}))
            self.assertEqual(observation.check_flow('M07', workspace, first, traces, before, after_first, snapshot(workspace))['status'], 'fail')
            state_file.write_text(json.dumps({'version': 1, 'observations': rows}))
            source = workspace/'export.py'
            source.write_bytes(source.read_bytes().replace(b'\n', b'\r\n'))
            self.assertEqual(observation.check_flow('M07', workspace, first, traces, before, after_first, snapshot(workspace))['status'], 'fail')

    def test_fallback_fixture_has_current_and_retired_clues_without_grading_instructions(self):
        files = observation.fixture('M08')
        self.assertIn('status=superseded', files['.aitasks/lessons.md'])
        self.assertIn('retries=0', files['CONTRACT.md'])
        self.assertFalse(any(name.startswith('.agents/') for name in files))
        self.assertNotIn('评分', ''.join(files.values()))


if __name__ == '__main__':
    unittest.main()
