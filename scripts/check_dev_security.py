"""Experimental PR3-only security policy; production check_security is unchanged.

Owner approved on 2026-10-01: temporary benchmark image, no production data,
accept linux-libc-dev header findings, delete image after confirming benchmarks.
This is explicit risk acceptance, not a claim of zero CVEs or a kernel assessment.
"""

from collections import Counter
from datetime import date
import json
from pathlib import Path
import sys

EXPIRES = date(2026, 10, 15)  # Exclusive; fail closed if experiments run longer.
SOURCE = "2a5c9c81b2e77f10aad25582679c8d344c3f6694"
HEADER_VERSION = "6.8.0-55.57"


def evaluate(report, today=None):
    today = today or date.today()
    if (
        report.get("SchemaVersion") != 2
        or report.get("ArtifactType") != "container_image"
        or not isinstance(report.get("Results"), list)
        or not report["Results"]
    ):
        raise ValueError("Missing or invalid container vulnerability results")
    os_info = report.get("Metadata", {}).get("OS", {})
    active = (
        today < EXPIRES
        and os_info.get("Family") == "ubuntu"
        and os_info.get("Name") == "24.04"
    )
    counts = Counter()
    accepted, blocked = [], []
    for result in report["Results"]:
        if not isinstance(result, dict):
            raise ValueError("Malformed result")
        issues = result.get("Vulnerabilities")
        if issues is None:
            issues = []
        if not isinstance(issues, list):
            raise ValueError("Malformed vulnerabilities")
        for issue in issues:
            if not isinstance(issue, dict):
                raise ValueError("Malformed vulnerability")
            severity = issue.get("Severity")
            if severity not in {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise ValueError("Unrecognized vulnerability severity")
            counts[severity] += 1
            if severity not in {"HIGH", "CRITICAL"}:
                continue
            if not all(
                isinstance(issue.get(key), str) and issue[key]
                for key in ("PkgName", "InstalledVersion", "VulnerabilityID")
            ):
                raise ValueError("Missing vulnerability identity")
            record = {
                "cve": issue["VulnerabilityID"],
                "package": issue["PkgName"],
                "installed": issue["InstalledVersion"],
                "severity": severity,
                "fixed": issue.get("FixedVersion"),
            }
            if (
                active
                and result.get("Class") == "os-pkgs"
                and result.get("Type") == "ubuntu"
                and issue["PkgName"] == "linux-libc-dev"
                and issue["InstalledVersion"] == HEADER_VERSION
            ):
                accepted.append(record)
            else:
                blocked.append(record)
    return {
        "gate_passed": not blocked,
        "zero_high_critical": not accepted and not blocked,
        "raw_severity_counts": dict(counts),
        "exception_active": active,
        "exception_expires_exclusive": EXPIRES.isoformat(),
        "source_commit": SOURCE,
        "scope": "temporary experimental benchmark image only; no production data; delete after benchmarks",
        "accepted_header_findings": accepted,
        "blocking_findings": blocked,
    }


if __name__ == "__main__":
    # Bind policy to the actual baked manifest, not just a conveniently named tag.
    manifest = Path(sys.argv[2]).read_text().splitlines()
    if f"source_commit={SOURCE}" not in manifest:
        sys.exit("Refused: exception is restricted to exact PR3 source")
    try:
        result = evaluate(json.loads(Path(sys.argv[1]).read_text()))
    except (ValueError, TypeError, AttributeError) as error:
        sys.exit(f"Refused malformed security evidence: {error}")
    print(json.dumps(result, indent=2))
    if not result["gate_passed"]:
        sys.exit("Security gate refused: non-exempt HIGH/CRITICAL findings remain")
