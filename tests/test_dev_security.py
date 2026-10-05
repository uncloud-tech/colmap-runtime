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
        return evaluate(
            report,
            today=today,
            base_image="nvidia/cuda:12.8.1-devel-ubuntu24.04@sha256:4b9ed5fa8361736996499f64ecebf25d4ec37ff56e4d11323ccde10aa36e0c43",
        )

    def python_report(self):
        report = self.report()
        report["Metadata"]["ImageID"] = (
            "sha256:37f08c781f6fa456c20fe5faaef9d733ef2b7523c8925e4d83c9d1fb342739e7"
        )
        report["Results"] = [
            {
                "Class": "lang-pkgs",
                "Type": "python-pkg",
                "Vulnerabilities": [
                    {
                        "PkgName": package,
                        "InstalledVersion": version,
                        "VulnerabilityID": cve,
                        "Severity": "HIGH",
                    }
                    for package, version, cve in (
                        ("msgpack", "1.1.2", "GHSA-6v7p-g79w-8964"),
                        ("setuptools", "70.3.0", "CVE-2025-47273"),
                        ("urllib3", "2.7.0", "CVE-2026-97687"),
                        ("urllib3", "2.7.0", "CVE-2026-97689"),
                    )
                ],
            }
        ]
        return report

    def test_exact_python_findings_accepted_without_erasing_risk(self):
        report = self.python_report()
        report["Results"] += self.report()["Results"]
        result = self.check(report, today=date(2026, 10, 5))
        self.assertTrue(result["gate_passed"])
        self.assertFalse(result["zero_high_critical"])
        self.assertEqual(len(result["accepted_python_findings"]), 4)
        self.assertEqual(len(result["accepted_header_findings"]), 1)
        self.assertEqual(result["raw_severity_counts"], {"HIGH": 4, "CRITICAL": 1})
        self.assertEqual(result["blocking_findings"], [])

    def test_python_exception_expires_at_start_of_october_15_utc(self):
        for day, passed in ((14, True), (15, False), (16, False)):
            with self.subTest(day=day):
                self.assertEqual(
                    self.check(self.python_report(), today=date(2026, 10, day))[
                        "gate_passed"
                    ],
                    passed,
                )

    def test_python_exception_does_not_follow_other_image_or_base(self):
        for image in (None, "sha256:" + "a" * 64):
            report = self.python_report()
            report["Metadata"]["ImageID"] = image
            self.assertFalse(self.check(report)["gate_passed"])
        self.assertFalse(
            evaluate(self.python_report(), today=date(2026, 10, 5), base_image="other")[
                "gate_passed"
            ]
        )

    def test_python_exception_requires_exact_ecosystem_and_high_tuple(self):
        for key, value in (
            ("PkgName", "other"),
            ("InstalledVersion", "1.1.3"),
            ("VulnerabilityID", "CVE-NEW"),
            ("Severity", "CRITICAL"),
        ):
            report = self.python_report()
            report["Results"][0]["Vulnerabilities"][0][key] = value
            result = self.check(report)
            self.assertFalse(result["gate_passed"])
            self.assertEqual(len(result["blocking_findings"]), 1)
        for key, value in (("Class", "os-pkgs"), ("Type", "other")):
            report = self.python_report()
            report["Results"][0][key] = value
            self.assertFalse(self.check(report)["gate_passed"])

    def test_unrelated_high_remains_blocking_alongside_accepted_python(self):
        report = self.python_report()
        report["Results"][0]["Vulnerabilities"].append(
            {
                "PkgName": "numpy",
                "InstalledVersion": "2.5.3",
                "VulnerabilityID": "CVE-UNAPPROVED",
                "Severity": "HIGH",
            }
        )
        result = self.check(report)
        self.assertFalse(result["gate_passed"])
        self.assertEqual(len(result["accepted_python_findings"]), 4)
        self.assertEqual(result["blocking_findings"][0]["cve"], "CVE-UNAPPROVED")

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

    def test_wrong_or_missing_base_cannot_receive_exception(self):
        for base in (None, "nvidia/cuda:other@sha256:" + "a" * 64):
            with self.subTest(base=base):
                result = evaluate(
                    self.report(), today=date(2026, 10, 4), base_image=base
                )
                self.assertFalse(result["gate_passed"])
                self.assertFalse(result["exception_active"])

    def test_expired_exception_blocks_findings(self):
        result = self.check(self.report(), today=date(2026, 10, 15))
        self.assertFalse(result["gate_passed"])
        self.assertFalse(result["exception_active"])

    def test_invalid_report_fails_closed(self):
        for report in ({}, self.report(severity="INVALID")):
            with self.subTest(report=report), self.assertRaises(ValueError):
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
        guard = next(
            expression
            for expression in re.findall(r"awk '([^']+)'", dockerfile)
            if expression.startswith("/^(Remv|Purg) /")
        )
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
