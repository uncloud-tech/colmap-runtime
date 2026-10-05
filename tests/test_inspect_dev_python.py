import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InspectDevPythonTests(unittest.TestCase):
    def run_inspection(self, directory):
        return subprocess.run(
            ["bash", str(ROOT / "scripts/inspect_dev_python.sh")],
            env={**os.environ, "INSPECTION_ROOT": str(directory)},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_empty_scoped_filesystem_reports_absent_not_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_inspection(directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("python_candidates=0", result.stdout)
            self.assertIn("locked_interpreter_match=no", result.stdout)
            self.assertIn("inspection_scope=", result.stdout)

    def test_existing_interpreter_is_executed_and_hashed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            bindir = Path(directory) / "usr/bin"
            bindir.mkdir(parents=True)
            (bindir / "python3").symlink_to(sys.executable)
            (bindir / "python").symlink_to(sys.executable)
            result = self.run_inspection(directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("python_candidates=1", result.stdout)
            self.assertIn("python_executable_sha256=", result.stdout)
            self.assertIn('"version_info":', result.stdout)
            self.assertIn('"distributions":', result.stdout)


if __name__ == "__main__":
    unittest.main()
