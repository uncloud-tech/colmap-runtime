import copy
import importlib
from pathlib import Path
import tempfile
import unittest

from dev.python.locked_env import COLMAP_SHA, PREFIX, PYTHON_SHA, load_lock


class RuntimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.runtime = importlib.import_module("dev.python.verify_runtime")
        except ModuleNotFoundError:
            self.runtime = None
        self.assertIsNotNone(self.runtime, "runtime verifier is missing")
        self.lock = load_lock(Path("dev/python/environment-lock.json"))

    def evidence(self):
        native = {
            "binary-sha256.txt": COLMAP_SHA + "  /opt/colmap-pr8/bin/colmap\n",
            "native-env.txt": self.runtime.NATIVE_ENV,
            "native-library-files.sha256": "native library hash\n",
        }
        libraries = [
            {
                "path": str(
                    PREFIX
                    / "lib/python3.14/site-packages/nvidia"
                    / component
                    / "lib"
                    / name
                ),
                "sha256": "a" * 64,
            }
            for component, name in (
                ("cuda_runtime", "libcudart.so.12"),
                ("curand", "libcurand.so.10"),
            )
        ]
        return {
            "schema_version": 1,
            "interpreter": {
                "path": str(PREFIX / "bin/python3.14"),
                "prefix": str(PREFIX),
                "base_prefix": str(PREFIX),
                "version": "3.14.7",
                "sha256": PYTHON_SHA,
            },
            "aliases": {
                "/usr/local/bin/" + name: str(PREFIX / "bin/python3.14")
                for name in ("python", "python3")
            },
            "distributions": {
                r["name"]: r["version"] for r in self.lock["dependency_artifacts"]
            }
            | {"pip": "26.2.1"},
            "native_before": native,
            "native_after": copy.deepcopy(native),
            "python_libraries": libraries,
            "cpu_smoke": {"numeric": True, "rendering": True, "pycolmap": True},
            "verification_scope": {
                "gpu_validated": False,
                "mps_validated": False,
                "reference_map_gate_passed": False,
            },
        }

    def test_valid_identity(self):
        self.runtime.validate_runtime(self.evidence(), self.lock)

    def test_boolean_schema_wrong_prefix_or_package_rejected(self):
        for mutate in (
            lambda e: e.update(schema_version=True),
            lambda e: e["interpreter"].update(prefix="/usr"),
            lambda e: e["distributions"].update(pip="24.0"),
            lambda e: e["aliases"].update(
                {"/usr/local/bin/python": "/usr/bin/python3"}
            ),
        ):
            evidence = self.evidence()
            mutate(evidence)
            with self.assertRaises(ValueError):
                self.runtime.validate_runtime(evidence, self.lock)

    def test_native_child_resolution_and_environment_checked_after_imports(self):
        expected = {"native-library-resolution.txt": "\tlib.so => /native/lib.so\n"}
        text = "\tlib.so => /native/lib.so (0x123456)\n"
        self.runtime.validate_native_child(text, self.runtime.NATIVE_ENV, expected)
        with self.assertRaises(ValueError):
            self.runtime.validate_native_child(
                text.replace("/native/", "/wheel/"), self.runtime.NATIVE_ENV, expected
            )
        with self.assertRaises(ValueError):
            self.runtime.validate_native_child(text, "changed environment", expected)

    def test_native_library_or_global_env_change_rejected(self):
        for key in (
            "native-library-files.sha256",
            "native-env.txt",
            "binary-sha256.txt",
        ):
            evidence = self.evidence()
            evidence["native_after"][key] = "changed"
            with self.assertRaises(ValueError):
                self.runtime.validate_runtime(evidence, self.lock)

    def test_python_cuda_must_be_process_local(self):
        evidence = self.evidence()
        evidence["python_libraries"][0]["path"] = (
            "/usr/local/cuda/lib64/libcudart.so.12"
        )
        with self.assertRaises(ValueError):
            self.runtime.validate_runtime(evidence, self.lock)

    def test_gpu_claim_is_not_inherited(self):
        evidence = self.evidence()
        evidence["verification_scope"]["gpu_validated"] = True
        with self.assertRaises(ValueError):
            self.runtime.validate_runtime(evidence, self.lock)

    def test_installed_file_mutation_or_addition_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            (prefix / "module.py").write_text("original")
            inventory = self.runtime.file_inventory(prefix)
            self.runtime.verify_installed_files(prefix, inventory)
            (prefix / "module.py").write_text("changed")
            with self.assertRaises(ValueError):
                self.runtime.verify_installed_files(prefix, inventory)
            (prefix / "module.py").write_text("original")
            (prefix / "extra.py").write_text("extra")
            with self.assertRaises(ValueError):
                self.runtime.verify_installed_files(prefix, inventory)

    def test_escaping_installed_link_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            (prefix / "escape").symlink_to("/etc/passwd")
            with self.assertRaises(ValueError):
                self.runtime.file_inventory(prefix)
