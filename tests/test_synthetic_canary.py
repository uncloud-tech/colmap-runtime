import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class SyntheticCanaryTests(unittest.TestCase):
    def load(self):
        path = ROOT / "scripts/synthetic_canary.py"
        self.assertTrue(path.exists(), "missing synthetic canary")
        spec = importlib.util.spec_from_file_location("synthetic_canary", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_fusion_requests_ply_not_default_binary_directory(self):
        module = self.load()
        native = Mock()
        options = {"min_num_pixels": 2}
        module.fuse_points(native, Path("fused.ply"), Path("dense"), options)
        native.stereo_fusion.assert_called_once_with(
            Path("fused.ply"),
            Path("dense"),
            input_type="geometric",
            options=options,
            output_type="ply",
        )

    def test_cpu_api_check_is_explicit_and_worker_is_bounded(self):
        module = self.load()
        with (
            patch.object(
                module.sys,
                "argv",
                ["canary", "--output", "/tmp/example", "--check-api"],
            ),
            patch.object(module.subprocess, "run") as run,
        ):
            module.main()
            self.assertIn("--check-api", run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs["timeout"], 300)
        with (
            patch.object(module.sys, "argv", ["canary", "--output", "/tmp/example"]),
            patch.object(module.subprocess, "run") as run,
        ):
            module.main()
            self.assertNotIn("--check-api", run.call_args.args[0])

    def test_generated_fixture_has_consistent_camera_tracks(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "new"
            manifest = module.generate_fixture(root)
            self.assertEqual(manifest["views"], 5)
            self.assertEqual(len(list((root / "images").glob("*.png"))), 5)
            lines = (root / "sparse/images.txt").read_text().splitlines()
            self.assertEqual(len(lines), 10)
            point_lines = (root / "sparse/points3D.txt").read_text().splitlines()
            self.assertGreater(len(point_lines), 100)
            for line in point_lines:
                fields = line.split()
                self.assertEqual(float(fields[3]), 4.0)
                self.assertEqual(len(fields[8:]), 10)
            for index in range(0, 10, 2):
                camera_x = -float(lines[index].split()[5])
                obs = lines[index + 1].split()
                point = point_lines[int(obs[2]) - 1].split()
                u, v = module.project(float(point[1]), float(point[2]), camera_x)
                self.assertAlmostEqual(float(obs[0]), u, places=5)
                self.assertAlmostEqual(float(obs[1]), v, places=5)
            with self.assertRaises(FileExistsError):
                module.generate_fixture(root)

    def test_acceptance_rejects_empty_or_incorrect_geometry(self):
        module = self.load()
        for points in ([], [(0, 0, 7)] * 200, [(0, 0, float("nan"))] * 200):
            with self.assertRaises(ValueError):
                module.validate_points(points)
        report = module.validate_points([(0, 0, 4.01)] * 200)
        self.assertEqual(report["points"], 200)
        self.assertLess(report["median_depth_error"], 0.02)


if __name__ == "__main__":
    unittest.main()
