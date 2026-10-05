"""Base-digest-scoped dev security policy; production check_security is unchanged.

Owner approved on 2026-10-01: temporary benchmark image, no production data,
accept linux-libc-dev header findings, delete image after confirming benchmarks.
This is explicit risk acceptance, not a claim of zero CVEs or a kernel assessment.
"""

from collections import Counter
from datetime import UTC, date, datetime
import json
from pathlib import Path
import sys

EXPIRES = date(2026, 10, 15)  # Exclusive; fail closed if experiments run longer.
# Owner clarified on 2026-10-04: scope to the identical base, not COLMAP source.
BASE_IMAGE = "nvidia/cuda:12.8.1-devel-ubuntu24.04@sha256:4b9ed5fa8361736996499f64ecebf25d4ec37ff56e4d11323ccde10aa36e0c43"
HEADER_VERSION = "6.8.0-55.57"
# Owner signoff 2026-10-05: these four HIGH findings, this image only.
PYTHON_IMAGE_ID = (
    "sha256:37f08c781f6fa456c20fe5faaef9d733ef2b7523c8925e4d83c9d1fb342739e7"
)
PYTHON_FINDINGS = frozenset(
    {
        ("msgpack", "1.1.2", "GHSA-6v7p-g79w-8964", "HIGH"),
        ("setuptools", "70.3.0", "CVE-2025-47273", "HIGH"),
        ("urllib3", "2.7.0", "CVE-2026-97687", "HIGH"),
        ("urllib3", "2.7.0", "CVE-2026-97689", "HIGH"),
    }
)


def evaluate(report, today=None, base_image=None):
    today = today or datetime.now(UTC).date()
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
        and base_image == BASE_IMAGE
        and os_info.get("Family") == "ubuntu"
        and os_info.get("Name") == "24.04"
    )
    image_id = report.get("Metadata", {}).get("ImageID")
    python_active = active and image_id == PYTHON_IMAGE_ID
    counts = Counter()
    accepted, accepted_python, blocked = [], [], []
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
            elif (
                python_active
                and result.get("Class") == "lang-pkgs"
                and result.get("Type") == "python-pkg"
                and (
                    issue["PkgName"],
                    issue["InstalledVersion"],
                    issue["VulnerabilityID"],
                    severity,
                )
                in PYTHON_FINDINGS
            ):
                accepted_python.append(record)
            else:
                blocked.append(record)
    return {
        "gate_passed": not blocked,
        "zero_high_critical": not accepted and not accepted_python and not blocked,
        "raw_severity_counts": dict(counts),
        "exception_active": active,
        "python_exception_active": python_active,
        "python_exception_image_id": PYTHON_IMAGE_ID,
        "report_image_id": image_id,
        "exception_expires_exclusive": EXPIRES.isoformat(),
        "base_image": base_image,
        "scope": "temporary experimental benchmark image only; no production data; delete after benchmarks",
        "accepted_header_findings": accepted,
        "accepted_python_findings": accepted_python,
        "blocking_findings": blocked,
    }


if __name__ == "__main__":
    # Bind the exception to the actual baked base identity, never just a tag.
    manifest = Path(sys.argv[2]).read_text().splitlines()
    bases = [
        line.removeprefix("base_image=")
        for line in manifest
        if line.startswith("base_image=")
    ]
    if len(bases) != 1:
        sys.exit("Refused: missing or ambiguous baked base identity")
    try:
        result = evaluate(
            json.loads(Path(sys.argv[1]).read_text()), base_image=bases[0]
        )
    except (ValueError, TypeError, AttributeError) as error:
        sys.exit(f"Refused malformed security evidence: {error}")
    print(json.dumps(result, indent=2))
    if not result["gate_passed"]:
        sys.exit("Security gate refused: non-exempt HIGH/CRITICAL findings remain")
