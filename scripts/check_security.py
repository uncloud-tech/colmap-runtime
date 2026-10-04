"""Fail closed on HIGH/CRITICAL findings; retain lower-severity counts for review."""

from collections import Counter
import json
from pathlib import Path
import sys


def check(report):
    if (
        report.get("SchemaVersion") != 2
        or report.get("ArtifactType") != "container_image"
        or not isinstance(report.get("Results"), list)
        or not report["Results"]
    ):
        raise ValueError("Missing or invalid container vulnerability results")
    counts = Counter()
    for result in report["Results"]:
        for issue in result.get("Vulnerabilities") or []:
            severity = issue.get("Severity")
            if severity not in {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise ValueError("Unrecognized vulnerability severity")
            counts[severity] += 1
    if counts["HIGH"] or counts["CRITICAL"]:
        raise ValueError(
            f"Security gate refused: {counts['HIGH']} HIGH, {counts['CRITICAL']} CRITICAL"
        )
    return dict(counts)


if __name__ == "__main__":
    print(json.dumps(check(json.loads(Path(sys.argv[1]).read_text()))))
