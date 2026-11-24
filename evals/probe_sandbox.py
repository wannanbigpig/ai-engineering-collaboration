"""Run the grader and candidate together in a disposable, offline Python container."""
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import uuid


IMAGE = "python:3.12-alpine@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89"
PROBE_TIMEOUT = 15

# The trusted grader compares plain JSON values. Candidate imports and calls happen
# in its child process, so a candidate exit cannot skip the grader's assertions.
CANDIDATE_RESULT_CODE = '''import json
import subprocess
import sys


def candidate_result(source):
    collector = """import json
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.getcwd())
response = sys.stdout
values = {}
with redirect_stdout(sys.stderr):
    exec(compile(sys.argv[1], '<candidate probe>', 'exec'), values)
    payload = json.dumps(values['result'], allow_nan=False)
print(payload, file=response)
"""
    child = subprocess.run([sys.executable, '-I', '-B', '-S', '-c', collector, source],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    if child.stderr:
        print(child.stderr, file=sys.stderr, end='')
    if child.returncode:
        raise AssertionError(f'candidate process exited {child.returncode}')
    try:
        return json.loads(child.stdout)
    except ValueError as error:
        raise AssertionError('candidate did not return probe data') from error

'''


def workspace_entry(entry):
    if entry.isfile() or entry.isdir() or entry.issym() or entry.islnk():
        return entry
    return None


def run(workspace: Path, script: str) -> subprocess.CompletedProcess:
    name = f"skill-probe-{uuid.uuid4().hex}"
    command = [
        "docker", "run", "--rm", "--pull=never", "--name", name, "--interactive",
        "--network=none", "--read-only", "--user=65534:65534", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=64", "--memory=256m",
        "--tmpfs", "/work:rw,nosuid,nodev,mode=1777", "--workdir=/work",
        IMAGE, "env", "-i", "PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/work",
        # Keep sh as PID 1 so timeout can signal the Python child.
        "sh", "-c", 'tar -xf - && timeout -s KILL "$2" python -I -B -S -c "$1"; exit $?',
        "probe", script, str(PROBE_TIMEOUT),
    ]
    # Copy ordinary files and links, never follow workspace links into the host.
    # The daemon can be remote: no host path, socket or credentials are mounted.
    with tempfile.TemporaryFile() as source:
        with tarfile.open(fileobj=source, mode="w", dereference=False) as archive:
            for item in sorted(workspace.iterdir()):
                if item.name != ".git":
                    archive.add(item, arcname=item.name, filter=workspace_entry)
        source.seek(0)
        try:
            return subprocess.run(command, stdin=source, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=PROBE_TIMEOUT + 10)
        except subprocess.TimeoutExpired:
            # Killing the Docker client alone can leave the container running.
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=10)
            raise


if __name__ == "__main__" and sys.argv[1:] == ["--image"]:
    print(IMAGE)
