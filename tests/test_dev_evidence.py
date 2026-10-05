import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "dev_targets", ROOT / "scripts/check_dev_targets.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DevEvidenceTests(unittest.TestCase):
    SASS = "arch = sm_89\nFunction : _ZComputeInitialCost\nFunction : _ZSweepFromTopToBottom\nFunction : _ZInitNormalMap\n"
    PTX = ".version 8.7\n.target sm_90\n.visible .entry _ZComputeInitialCost() {}\n.visible .entry _ZSweepFromTopToBottom() {}\n.visible .entry _ZInitNormalMap() {}\n"

    def test_matches_functions_in_sm89_sass_and_sm90_ptx(self):
        result = module.verify(self.SASS, self.PTX, patch_match=True)
        self.assertEqual(len(result), 3)

    def test_old_fleet_architecture_is_rejected(self):
        with self.assertRaises(ValueError):
            module.verify(self.SASS.replace("sm_89", "sm_86"), self.PTX)

    def test_native_blackwell_does_not_replace_ptx(self):
        with self.assertRaises(ValueError):
            module.verify(self.SASS + "\narch = sm_120\n", "", patch_match=True)

    def test_wrong_ptx_target_is_rejected(self):
        with self.assertRaises(ValueError):
            module.verify(
                self.SASS, self.PTX.replace("sm_90", "sm_86"), patch_match=True
            )

    def test_missing_kernel_in_ptx_is_rejected(self):
        with self.assertRaises(ValueError):
            module.verify(
                self.SASS,
                self.PTX.replace("_ZInitNormalMap", "_ZOther"),
                patch_match=True,
            )

    def test_functions_in_wrong_module_cannot_fill_coverage(self):
        with self.assertRaises(ValueError):
            module.verify(
                self.SASS,
                self.PTX.replace("sm_90", "sm_120") + "\n.version 8.7\n.target sm_90\n",
                patch_match=True,
            )

    def test_empty_or_missing_required_families_rejected(self):
        with self.assertRaises(ValueError):
            module.verify("", self.PTX, patch_match=True)
        with self.assertRaises(ValueError):
            module.verify(
                "arch = sm_86\nFunction : other\n",
                ".version 8.7\n.target sm_90\n.entry other(){}",
                patch_match=True,
            )

    def test_missing_library_object_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "mvs-objects.json").write_text(
                json.dumps(["patch_match_cuda.cu.o"])
            )
            with self.assertRaisesRegex(ValueError, "three CUDA objects"):
                module.main(directory)

    def test_workflow_keeps_recipe_and_fails_closed(self):
        workflow = (ROOT / ".github/workflows/build-dev.yml").read_text()
        self.assertNotIn(
            "/src/colmap-pr3/build", workflow.replace("/opt/src/colmap-pr3/build", "")
        )
        self.assertIn("scripts/collect_dev_evidence.sh", workflow)
        self.assertIn("scripts/check_dev_targets.py", workflow)
        self.assertNotIn("informational for dev", workflow)
        self.assertNotIn("recorded, not gated", workflow)
        self.assertNotIn("ubuntu22.04", workflow)
        self.assertIn("--network none", workflow)
        self.assertNotIn("colmap-dev:pr3 || true", workflow)
        native = workflow.split("  build:\n", 1)[1].split("  python:\n", 1)[0]
        self.assertLess(
            native.index("scripts/check_dev_targets.py"),
            native.index("docker push"),
        )
        self.assertLess(
            native.index("scripts/check_dev_security.py"),
            native.index("docker push"),
        )
        production = (ROOT / ".github/workflows/build.yml").read_text()
        self.assertIn("scripts/check_security.py", production)
        self.assertNotIn("check_dev_security.py", production)
        script = (ROOT / "scripts/collect_dev_evidence.sh").read_text()
        self.assertIn("--no-tests=error", script)
        self.assertIn("--dump-ptx", script)
        self.assertIn("--dump-sass", script)
        self.assertIn("/opt/deps/include", script)


if __name__ == "__main__":
    unittest.main()
