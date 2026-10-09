#!/usr/bin/env python3
"""Offline installer for the R570 image's isolated Python closure.

Adapted from the existing dev/python pipeline (``install.py`` + ``locked_env.py``)
so the exact locked bytes and the byte-identical ``environment-lock.json`` are
reused without importing that module tree.  The lock SHA256, the CPython archive
SHA256 and the 16 wheel hashes are enforced before any installation, and the
installed distribution closure must equal the lock exactly, with pip 26.2.1.

The CUDA 12.9 runtime wheels remain inside site-packages only; no loader
configuration is added for them, so they can never satisfy the native loader.
"""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

PREFIX = Path("/opt/colmap-python")
LOCK_SHA256 = "a22ac04ee8febc9f46f281d7b01d200e73e75f2d380bbc02b0bffc4992ee45cd"
CPYTHON_ARCHIVE = (
    "cpython-3.14.7+20260924-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
)
CPYTHON_SHA256 = "bd0d0568ccded07bbf1c87727230dc5dd0187e706a87da23c4de78388a229b78"
PYTHON_SHA256 = "5a91882290532b2719eaca77c0f3a7448bd73b9214e56df57bc59004560a80c6"
PYTHON_VERSION = "3.14.7"
PIP_VERSION = "26.2.1"
EXPECTED_ARTIFACT_ROWS = 17


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def load_lock(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != LOCK_SHA256:
        raise ValueError("environment lock is not the byte-identical lock")
    lock = json.loads(raw)
    rows = lock["artifacts"] + lock["dependency_artifacts"]
    if len(rows) != EXPECTED_ARTIFACT_ROWS:
        raise ValueError(f"expected {EXPECTED_ARTIFACT_ROWS} locked artifacts, got {len(rows)}")
    return lock


def verify_artifacts(artifacts, rows):
    for row in rows:
        name = row["uri"].rsplit("/", 1)[-1]
        path = artifacts / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"artifact missing: {name}")
        if path.stat().st_size != row["size_bytes"] or sha256(path) != row["sha256"]:
            raise ValueError(f"artifact size/hash mismatch: {name}")


def distribution_closure():
    records = list(importlib.metadata.distributions())
    installed = {
        canonical(dist.metadata["Name"]): dist.version for dist in records
    }
    if len(installed) != len(records):
        raise ValueError("duplicate installed distribution")
    return installed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    args = parser.parse_args(argv)

    lock = load_lock(args.lock)
    rows = lock["artifacts"] + lock["dependency_artifacts"]
    if sha256(PREFIX / "bin" / "python3.14") != PYTHON_SHA256:
        raise ValueError("interpreter identity does not match the lock")
    if platform.python_version() != PYTHON_VERSION:
        raise ValueError(f"unexpected interpreter version {platform.python_version()}")
    verify_artifacts(args.artifacts, rows)
    if sha256(args.artifacts / CPYTHON_ARCHIVE) != CPYTHON_SHA256:
        raise ValueError("CPython archive hash mismatch")

    python = str(PREFIX / "bin" / "python3.14")
    base = [python, "-I", "-B", "-m"]
    subprocess.run([*base, "ensurepip"], check=True)
    subprocess.run(
        [
            *base,
            "pip",
            "--isolated",
            "install",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "--only-binary=:all:",
            "--find-links",
            str(args.artifacts),
            "-r",
            str(args.requirements),
        ],
        check=True,
    )
    subprocess.run([*base, "pip", "--isolated", "check"], check=True)

    expected = {
        canonical(row["name"]): row["version"] for row in rows
        if row["uri"].endswith(".whl")
    } | {"pip": PIP_VERSION}
    installed = distribution_closure()
    if installed != expected:
        raise ValueError(f"installed distribution closure differs: {installed}")
    print(f"python closure ok: {len(rows) - 1} packages + pip {PIP_VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
