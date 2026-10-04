from datetime import date
from pathlib import Path
import re
import subprocess
import unittest

from scripts.check_dev_security import evaluate


class DevSecurityTests(unittest.TestCase):
    def report(
        self,
        package="linux-libc-dev",
        severity="CRITICAL",
        version="6.8.0-55.57",
        kind="ubuntu",
    ):
        return {
            "SchemaVersion": 2,
            "ArtifactType": "container_image",
            "Metadata": {"OS": {"Family": "ubuntu", "Name": "24.04"}},
            "Results": [
                {
                    "Class": "os-pkgs",
                    "Type": kind,
                    "Vulnerabilities": [
                        {
                            "PkgName": package,
                            "InstalledVersion": version,
                            "VulnerabilityID": "CVE-2026-53398",
                            "Severity": severity,
                        }
                    ],
                }
            ],
        }

    def check(self, report, today=date(2026, 10, 1)):
        return evaluate(report, today=today)

    def test_only_named_header_package_can_receive_exception(self):
        result = self.check(self.report())
        self.assertTrue(result["gate_passed"])
        self.assertFalse(result["zero_high_critical"])
        self.assertEqual(
            result["accepted_header_findings"][0]["package"], "linux-libc-dev"
        )
        self.assertEqual(result["blocking_findings"], [])

    def test_user_space_and_kernel_packages_still_block(self):
        for package in ("gpg", "stdlib", "linux-image-generic", "linux-modules-6.8.0"):
            with self.subTest(package=package):
                result = self.check(self.report(package=package))
                self.assertFalse(result["gate_passed"])
                self.assertEqual(len(result["blocking_findings"]), 1)

    def test_wrong_header_version_or_ecosystem_not_waived(self):
        self.assertFalse(self.check(self.report(version="other"))["gate_passed"])
        self.assertFalse(self.check(self.report(kind="gobinary"))["gate_passed"])

    def test_expired_exception_blocks_findings(self):
        result = self.check(self.report(), today=date(2026, 10, 15))
        self.assertFalse(result["gate_passed"])
        self.assertFalse(result["exception_active"])

    def test_invalid_report_fails_closed(self):
        for report in ({}, self.report(severity="INVALID")):
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    self.check(report)

    def test_clean_scan_has_no_exception_findings(self):
        result = self.check(self.report(package="gpg", severity="LOW"))
        self.assertTrue(result["gate_passed"])
        self.assertTrue(result["zero_high_critical"])
        self.assertEqual(result["accepted_header_findings"], [])

    def test_nsight_removal_guard_accepts_purge_and_rejects_extra_removals(self):
        dockerfile = (
            Path(__file__).resolve().parents[1] / "dev/Dockerfile"
        ).read_text()
        guard = re.search(r"awk '([^']+)'", dockerfile).group(1)
        allowed = "Purg cuda-nsight-compute-12-8 [12.8.1-1]\nPurg nsight-compute-2025.1.1 [2025.1.1.2-1]\n"
        for plan, expected in (
            (allowed, 0),
            ("", 1),
            (allowed + "Remv cuda-nvcc-12-8 [12.8.93-1]\n", 1),
            (allowed + "Purg linux-libc-dev [6.8.0-55.57]\n", 1),
        ):
            with self.subTest(plan=plan):
                result = subprocess.run(
                    ["awk", guard], input=plan, text=True, capture_output=True
                )
                self.assertEqual(result.returncode, expected)

    def test_wrong_os_cannot_receive_exception(self):
        report = self.report()
        report["Metadata"]["OS"]["Name"] = "22.04"
        self.assertFalse(self.check(report)["gate_passed"])


if __name__ == "__main__":
    unittest.main()
