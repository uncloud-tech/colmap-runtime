import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SecurityGateTests(unittest.TestCase):
    def test_high_findings_or_missing_report_fail_closed(self):
        path = ROOT / "scripts/check_security.py"
        self.assertTrue(path.exists(), "missing security acceptance gate")
        spec = importlib.util.spec_from_file_location("security", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = {
            "SchemaVersion": 2,
            "ArtifactType": "container_image",
            "Results": [{"Vulnerabilities": [{"Severity": "MEDIUM"}]}],
        }
        self.assertEqual(module.check(report)["MEDIUM"], 1)
        for value in [
            {},
            {"SchemaVersion": 2, "ArtifactType": "container_image", "Results": None},
            {
                "SchemaVersion": 2,
                "ArtifactType": "container_image",
                "Results": [{"Vulnerabilities": [{"Severity": "HIGH"}]}],
            },
        ]:
            with self.assertRaises(ValueError):
                module.check(value)

    def test_final_stage_does_not_inherit_installer_layers(self):
        text = (ROOT / "image/Dockerfile").read_text()
        self.assertIn("AS base", text)
        self.assertIn("FROM base AS builder", text)
        self.assertIn("FROM base AS runtime", text)
        self.assertIn("upgrade -y", text)
        self.assertIn(
            "COPY --from=builder /opt/colmap-runtime /opt/colmap-runtime", text
        )
        self.assertIn("--require-installer-free", text)


if __name__ == "__main__":
    unittest.main()
