from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/aitasks-maintenance"


class SkillCommandExampleTest(unittest.TestCase):
    def test_documented_read_only_commands_work_with_space_containing_paths(self) -> None:
        text = (SKILL / "references/maintenance.md").read_text(encoding="utf-8")
        block = text.split("```bash\n", 1)[1].split("```", 1)[0]
        # Execute only the documented read-only operations in a temporary project.
        commands = [
            line for line in block.splitlines()
            if line.startswith("python3 ")
            and (line.endswith(" status") or " find-lessons " in line or line.endswith(" cleanup"))
        ]
        self.assertEqual(len(commands), 4)
        shells = [name for name in ("bash", "zsh") if shutil.which(name)]
        if not shells:
            self.skipTest("Neither bash nor zsh is available")
        with tempfile.TemporaryDirectory(prefix="skill examples ") as directory:
            root = Path(directory)
            copied = root / "skill copy"
            shutil.copytree(SKILL, copied)
            project = root / "project with spaces"
            project.mkdir()
            environment = dict(os.environ)
            environment.update(
                AITASKS_TOOL=str(copied / "scripts/maintain_aitasks.py"),
                AITASKS_PROJECT=str(project),
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
                        self.assertTrue(result.stdout.strip())
                        self.assertEqual(list(project.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
