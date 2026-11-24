"""Contract probe scoring and real container boundary tests."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


EVALS = Path(__file__).resolve().parents[1] / 'evals'
SPEC = importlib.util.spec_from_file_location('behavior_eval', EVALS / 'behavior_eval.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
sandbox = runner.probe_sandbox


class ProbeScoringTests(unittest.TestCase):
    def test_zero_exit_without_grader_completion_fails(self):
        with patch.object(sandbox, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            result = runner.run_contract_probe(Path.cwd(), 'assert True')
        self.assertEqual(result['status'], 'fail', result)
        self.assertIn('grader did not complete', result['reason'])

    def test_missing_engine_leaves_both_kinds_of_required_evidence_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app.py').write_text('def clamp(value): return max(value, 0)')
            with patch.dict(os.environ, {'PATH': str(root)}):
                for scenario in ('02', 'X02'):
                    with self.subTest(scenario=scenario):
                        result = runner.functional_check(scenario, root)
                        self.assertEqual(result['status'], 'unverified', result)
                        self.assertIs(result['required_evidence_unverified'], True)

    def test_engine_failure_and_loopback_unavailability_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            for scenario, code, message in [
                ('02', 125, 'container startup failed'), ('X02', 126, 'command unavailable'),
                ('X03', 127, 'command not found'), ('X01', 77, 'loopback unavailable: bind failed'),
            ]:
                with self.subTest(scenario=scenario, code=code), patch.object(
                    sandbox, 'run', return_value=subprocess.CompletedProcess([], code, '', message)
                ):
                    result = runner.functional_check(scenario, workspace)
                    self.assertEqual(result['status'], 'unverified', result)
                    self.assertTrue(runner.required_machine_evidence_unverified({'contract_probe': result}))

    def test_timed_out_probe_leaves_required_evidence_unverified(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                sandbox, 'run', side_effect=subprocess.TimeoutExpired('docker run', 15)):
            result = runner.functional_check('X01', Path(directory))
            self.assertEqual(result['status'], 'unverified', result)
            self.assertTrue(result['required_evidence_unverified'])


class ContainerProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mode = os.environ.get('REQUIRE_PROBE_CONTAINER')
        if mode == '0':
            raise unittest.SkipTest('the compatibility suite runs unit tests only')
        docker = shutil.which('docker')
        ready = docker and subprocess.run([docker, 'image', 'inspect', sandbox.IMAGE],
                                           capture_output=True, timeout=15).returncode == 0
        if not ready:
            message = f'Docker must be running with the probe image {sandbox.IMAGE} available'
            if mode == '1':
                raise AssertionError(message)
            raise unittest.SkipTest(message)

    def test_candidate_exceeding_its_deadline_fails(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sandbox, 'PROBE_TIMEOUT', 1):
            result = runner.run_contract_probe(Path(directory), 'import time; time.sleep(3)')
            self.assertEqual(result['status'], 'fail', result)
            self.assertEqual(result['exit_code'], 137)

    def test_invalid_function_and_experience_results_fail_with_host_optimization(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'PYTHONOPTIMIZE': '1'}):
            workspace = Path(directory)
            (workspace / 'app.py').write_text('def clamp(value): return 99')
            (workspace / 'refund.py').write_text('def refund(ledger, request_id, amount): return {}')
            for scenario in ('02', 'X02'):
                with self.subTest(scenario=scenario):
                    result = runner.functional_check(scenario, workspace)
                    self.assertEqual(result['status'], 'fail', result)
                    self.assertIn('AssertionError', result['stderr'])

    def test_clean_exit_without_candidate_results_fails(self):
        fixtures = (
            ('02', 'app.py', 'raise SystemExit(0)\n'),
            ('X02', 'refund.py', 'def refund(ledger, request_id, amount):\n    raise SystemExit(0)\n'),
        )
        for scenario, filename, body in fixtures:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                (workspace / filename).write_text(body)
                result = runner.functional_check(scenario, workspace)
                self.assertEqual(result['status'], 'fail', result)
                self.assertIn('candidate did not return probe data', result['stderr'])

    def test_grader_uses_candidate_values_with_debug_output(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / 'app.py').write_text(
                'def clamp(value):\n    print("debug", value)\n    return max(0, value)\n')
            result = runner.functional_check('02', workspace)
            self.assertEqual(result['status'], 'pass', result)
            self.assertIn('debug -2', result['stderr'])
            self.assertEqual(result['stdout'], '')

    def test_container_checks_candidate_subprocess_output(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            files = runner.experience_fixture('X03')
            for name, text in files.items():
                (workspace / name).write_text(text)
            result = runner.functional_check('X03', workspace)
            self.assertEqual(result['status'], 'pass', result)
            cli = workspace / 'cli.py'
            cli.write_text(cli.read_text().replace('"CONNECT_FAILED"', '"WRONG_CODE"'))
            result = runner.functional_check('X03', workspace)
            self.assertEqual(result['status'], 'fail', result)

    def test_container_supports_offline_loopback_for_the_ui_scenario(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            for name, text in runner.experience_fixture('X01').items():
                (workspace / name).write_text(text, encoding='utf-8')
            result = runner.functional_check('X01', workspace)
            self.assertEqual(result['status'], 'pass', result)

    def test_writable_workspace_is_a_private_copy_and_root_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / 'workspace'
            workspace.mkdir()
            source = workspace / 'input.txt'
            source.write_text('original')
            (workspace / '.git').mkdir()
            (workspace / '.git/config').write_text('host repository metadata')
            sibling = root / 'host-only.txt'
            sibling.write_text('outside workspace')
            script = f"""import json
import os
import socket
from pathlib import Path
source = Path('input.txt')
original = source.read_text()
source.write_text('container change')
Path('temporary-output').write_text('temporary')
# Linux can enumerate down tunnel devices in a network namespace with no egress.
up_interfaces = sorted(name for _, name in socket.if_nameindex()
                       if int(Path('/sys/class/net', name, 'flags').read_text(), 16) & 1)
print(json.dumps({{
    'input': original,
    'updated_copy': source.read_text(),
    'read_only_root': bool(os.statvfs('/').f_flag & os.ST_RDONLY),
    'unprivileged': os.getuid() != 0,
    'up_interfaces': up_interfaces,
    'git_metadata': Path('.git/config').exists(),
    'host_sibling': Path({str(sibling)!r}).exists() or Path('../host-only.txt').exists(),
    'host_env': os.environ.get('PROBE_TEST_HOST_MARKER')
}}))
"""
            with patch.dict(os.environ, {'PROBE_TEST_HOST_MARKER': 'host-only'}):
                result = sandbox.run(workspace, script)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {
                'input': 'original', 'updated_copy': 'container change', 'read_only_root': True,
                'host_sibling': False, 'host_env': None, 'unprivileged': True,
                'up_interfaces': ['lo'], 'git_metadata': False,
            })
            self.assertEqual(source.read_text(), 'original')
            self.assertFalse((workspace / 'temporary-output').exists())


if __name__ == '__main__':
    unittest.main()
