"""Offline installer for the one image interpreter; never runs on import."""

import argparse
import importlib.metadata
from pathlib import Path
import platform
import subprocess
import sys
from urllib.parse import urlsplit

from dev.python.locked_env import (
    PREFIX,
    PYTHON_SHA,
    canonical,
    load_lock,
    requirements_text,
    sha256,
    verify_file,
)


def alias_targets(prefix):
    if prefix != PREFIX:
        raise ValueError("wrong shared prefix")
    return {
        Path("/usr/local/bin") / name: prefix / "bin/python3.14"
        for name in ("python", "python3")
    }


def installation_commands(prefix, artifacts, requirements):
    python = str(prefix / "bin/python3.14")
    base = [python, "-I", "-B", "-m"]
    return [
        [*base, "ensurepip"],
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
            str(artifacts),
            "-r",
            str(requirements),
        ],
        [*base, "pip", "--isolated", "check"],
    ]


def validate_installation_context(prefix, executable, version, executable_sha256):
    if (
        prefix != PREFIX
        or prefix.is_symlink()
        or executable != prefix / "bin/python3.14"
        or version != "3.14.7"
        or executable_sha256 != PYTHON_SHA
    ):
        raise ValueError("wrong shared prefix/interpreter identity")


def validate_requirements(text, lock):
    if text != requirements_text(lock):
        raise ValueError("requirements differ from exact locked wheel pins")


def distributions():
    records = list(importlib.metadata.distributions())
    result = {canonical(d.metadata["Name"]): d.version for d in records}
    if len(result) != len(records):
        raise ValueError("duplicate installed distribution")
    return result


def validate_distributions(installed, lock):
    expected = {
        canonical(row["name"]): row["version"] for row in lock["dependency_artifacts"]
    } | {"pip": "26.2.1"}
    if installed != expected:
        raise ValueError(f"installed distribution closure differs: {installed}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    validate_installation_context(
        Path(sys.prefix),
        Path(sys.executable),
        platform.python_version(),
        sha256(sys.executable),
    )
    lock = load_lock(PREFIX / "environment-lock.json")
    validate_requirements((args.artifacts / "requirements.txt").read_text(), lock)
    for row in lock["artifacts"] + lock["dependency_artifacts"]:
        verify_file(args.artifacts / urlsplit(row["uri"]).path.rsplit("/", 1)[-1], row)
    for command in installation_commands(
        PREFIX, args.artifacts, args.artifacts / "requirements.txt"
    ):
        subprocess.run(command, check=True)
    validate_distributions(distributions(), lock)


if __name__ == "__main__":
    main()
