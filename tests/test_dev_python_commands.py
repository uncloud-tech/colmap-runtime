import importlib
from pathlib import Path
import unittest

from dev.python.locked_env import PARENT, load_lock


class PythonBuildBoundaryTests(unittest.TestCase):
    def setUp(self):
        try:
            self.commands = importlib.import_module("scripts.dev_python_commands")
        except ModuleNotFoundError:
            self.commands = None
        self.assertIsNotNone(self.commands, "Python-only build boundary missing")

    def test_no_native_build_push_or_cache_export(self):
        commands = self.commands.validation_commands(
            Path("dev/python").resolve(), "colmap-dev:pr8-python"
        )
        self.assertEqual(
            commands[0], ["docker", "pull", "--platform", "linux/amd64", PARENT]
        )
        argv = commands[1]
        for flag in ("--load", "--network=none", "--platform", "linux/amd64"):
            self.assertIn(flag, argv)
        self.assertNotIn("--push", argv)
        self.assertFalse(any("cache-to" in arg or "cache-from" in arg for arg in argv))
        self.assertIn(str(Path("dev/python/Dockerfile").resolve()), argv)

    def test_wrong_context_rejected(self):
        with self.assertRaises(ValueError):
            self.commands.validation_commands(
                Path("dev").resolve(), "colmap-dev:pr8-python"
            )

    def test_extra_context_member_rejected(self):
        allowed = self.commands.allowed_context_paths(
            load_lock(Path("dev/python/environment-lock.json"))
        )
        self.commands.validate_context_inventory(allowed, allowed)
        for bad in (
            Path(".staged/artifacts/secret.key"),
            Path("photo.jpg"),
            Path("extra.whl"),
        ):
            with self.assertRaises(ValueError):
                self.commands.validate_context_inventory(allowed | {bad}, allowed)

    def test_native_config_and_platform_changes_rejected(self):
        parent = {
            "Architecture": "amd64",
            "Os": "linux",
            "Config": {"Env": ["LD_LIBRARY_PATH=native"], "Entrypoint": ["native"]},
        }
        self.commands.verify_configs(parent, parent)
        for changed in (
            parent | {"Architecture": "arm64"},
            parent | {"Config": parent["Config"] | {"Env": ["LD_LIBRARY_PATH=wheel"]}},
            parent | {"Config": parent["Config"] | {"Entrypoint": ["python"]}},
        ):
            with self.assertRaises(ValueError):
                self.commands.verify_configs(parent, changed)
