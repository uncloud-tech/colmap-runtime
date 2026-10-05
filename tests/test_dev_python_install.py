import importlib
from pathlib import Path
import unittest

from dev.python.locked_env import PYTHON_SHA, load_lock


class OfflineInstallerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.install = importlib.import_module("dev.python.install")
        except ModuleNotFoundError:
            self.install = None
        self.assertIsNotNone(self.install, "offline installer is missing")

    def test_aliases_share_interpreter(self):
        self.assertEqual(
            self.install.alias_targets(Path("/opt/colmap-python")),
            {
                Path("/usr/local/bin/python"): Path(
                    "/opt/colmap-python/bin/python3.14"
                ),
                Path("/usr/local/bin/python3"): Path(
                    "/opt/colmap-python/bin/python3.14"
                ),
            },
        )

    def test_no_index_resolution_or_upgrade(self):
        commands = self.install.installation_commands(
            Path("/opt/colmap-python"), Path("/input"), Path("/input/requirements.txt")
        )
        for flag in (
            "--isolated",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "--only-binary=:all:",
        ):
            self.assertIn(flag, commands[1])
        self.assertNotIn("--upgrade", commands[1])
        self.assertIn("ensurepip", commands[0])
        self.assertEqual(commands[2][-1], "check")

    def test_wrong_interpreter_prefix_or_version_refused(self):
        prefix = Path("/opt/colmap-python")
        self.install.validate_installation_context(
            prefix, prefix / "bin/python3.14", "3.14.7", PYTHON_SHA
        )
        for exe, version, digest in (
            (Path("/usr/bin/python3"), "3.14.7", PYTHON_SHA),
            (prefix / "bin/python3.14", "3.12.0", PYTHON_SHA),
            (prefix / "bin/python3.14", "3.14.7", "a" * 64),
        ):
            with self.assertRaises(ValueError):
                self.install.validate_installation_context(prefix, exe, version, digest)

    def test_exact_distribution_closure_and_bootstrap(self):
        lock = load_lock(Path("dev/python/environment-lock.json"))
        expected = {
            row["name"]: row["version"] for row in lock["dependency_artifacts"]
        } | {"pip": "26.2.1"}
        self.install.validate_distributions(expected, lock)
        for changed in (
            expected | {"pip": "24.0"},
            expected | {"unexpected": "1"},
            {k: v for k, v in expected.items() if k != "scipy"},
        ):
            with self.assertRaises(ValueError):
                self.install.validate_distributions(changed, lock)
