import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "verify_runtime", ROOT / "image/verify_runtime.py"
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.lock = {
            "python": {"version": "3.14.7"},
            "wheels": [{"name": "example", "version": "1.0"}],
        }

    def test_installer_modules_and_bundled_wheels_are_rejected(self):
        self.assertTrue(hasattr(verifier, "assert_installer_free"))
        for relative in [
            "lib/python3.14/site-packages/pip/__init__.py",
            "lib/python3.14/ensurepip/_bundled/pip.whl",
            "bin/pip3.14",
        ]:
            with (
                self.subTest(relative=relative),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                verifier.assert_installer_free(root)
                p = root / relative
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"fixture")
                with self.assertRaises(RuntimeError):
                    verifier.assert_installer_free(root)

    def test_wrong_python_fails_before_imports(self):
        with (
            patch.object(verifier.platform, "python_version", return_value="3.12.0"),
            self.assertRaisesRegex(RuntimeError, "Python version"),
        ):
            verifier.verify("cpu", self.lock)

    def test_wrong_dependency_fails_before_imports(self):
        with (
            patch.object(verifier.platform, "python_version", return_value="3.14.7"),
            patch.object(verifier.importlib.metadata, "version", return_value="2.0"),
            self.assertRaisesRegex(RuntimeError, "Version mismatch"),
        ):
            verifier.verify("cpu", self.lock)

    def test_loaded_cuda_must_use_pinned_pip_provider(self):
        self.assertTrue(
            hasattr(verifier, "cuda_providers"), "missing native-provider verification"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "cuda_runtime/lib/libcudart.so.12"
            curand = root / "curand/lib/libcurand.so.10"
            for path in (runtime, curand):
                path.parent.mkdir(parents=True)
                path.write_bytes(b"fixture")
            maps = (
                f"100-200 r-xp 0 00:00 0 {runtime}\n200-300 r-xp 0 00:00 0 {curand}\n"
            )
            result = verifier.cuda_providers(maps, root)
            self.assertEqual(result["libcudart.so.12"], str(runtime))
            with self.assertRaisesRegex(RuntimeError, "provider"):
                verifier.cuda_providers(
                    maps.replace(str(runtime), "/usr/local/cuda/lib64/libcudart.so.12"),
                    root,
                )
            with self.assertRaisesRegex(RuntimeError, "provider"):
                verifier.cuda_providers("", root)

    def test_cpu_import_failure_keeps_original_exception(self):
        cause = ImportError("libSM.so.6 missing")
        wrapped = RuntimeError("Cannot import backend")
        wrapped.__cause__ = cause
        with (
            patch.object(verifier.platform, "python_version", return_value="3.14.7"),
            patch.object(verifier.importlib.metadata, "version", return_value="1.0"),
            patch.object(verifier.importlib, "import_module", side_effect=wrapped),
        ):
            with self.assertRaises(RuntimeError) as caught:
                verifier.verify("cpu", self.lock)
            self.assertIs(caught.exception.__cause__, cause)

    def test_gpu_inventory_does_not_collect_hardware_identifiers(self):
        with (
            patch.object(verifier.platform, "python_version", return_value="3.14.7"),
            patch.object(verifier.importlib.metadata, "version", return_value="1.0"),
            patch.object(verifier.importlib, "import_module"),
            patch.dict(sys.modules, {"pycolmap": types.SimpleNamespace(has_cuda=True)}),
            patch.object(verifier, "cuda_providers", return_value={}),
            patch.object(
                verifier.subprocess,
                "check_output",
                return_value="0, Example GPU, 580.00\n",
            ) as gpu,
        ):
            result = verifier.verify("gpu", self.lock)
            command = gpu.call_args.args[0]
            self.assertIn("--query-gpu=index,name,driver_version", command)
            self.assertFalse(result["gpu_execution_validated"])

    def test_cpu_mode_never_claims_gpu_execution(self):
        self.assertTrue(
            hasattr(verifier, "cuda_providers"), "missing native-provider verification"
        )
        with (
            patch.object(verifier.platform, "python_version", return_value="3.14.7"),
            patch.object(verifier.importlib.metadata, "version", return_value="1.0"),
            patch.object(verifier.importlib, "import_module"),
            patch.dict(sys.modules, {"pycolmap": types.SimpleNamespace(has_cuda=True)}),
            patch.object(
                verifier, "cuda_providers", return_value={"libcudart.so.12": "/fixture"}
            ),
            patch.object(verifier.subprocess, "check_output") as gpu,
        ):
            result = verifier.verify("cpu", self.lock)
            self.assertFalse(result["gpu_execution_validated"])
            self.assertIn("cuda_providers", result)
            gpu.assert_not_called()


if __name__ == "__main__":
    unittest.main()
