"""Strict schema-2 envelope; native checker still accepts only schema 1."""

import argparse
import json
from pathlib import Path

from dev.python.locked_env import (
    ARCHIVE_SHA,
    COLMAP_SHA,
    LOCK_SHA,
    PARENT_DIGEST,
    PREFIX,
    PYTHON_SHA,
    load_lock,
    sha256,
)
from dev.python.verify_runtime import validate_runtime
from scripts.check_dev_contract import expected_native_contract, verify_native


def make_contract(native, runtime, runtime_manifest_sha256):
    if native != expected_native_contract(COLMAP_SHA):
        raise ValueError("native parent identity differs")
    return native | {
        "schema_version": 2,
        "native_parent_digest": PARENT_DIGEST,
        "environment_lock_sha256": LOCK_SHA,
        "python": {
            "prefix": str(PREFIX),
            "executable": str(PREFIX / "bin/python3.14"),
            "aliases": {
                "/usr/local/bin/" + n: str(PREFIX / "bin/python3.14")
                for n in ("python", "python3")
            },
            "version": "3.14.7",
            "release": "3.14.7+20260924",
            "archive_sha256": ARCHIVE_SHA,
            "executable_sha256": PYTHON_SHA,
            "bootstrap": {"pip": "26.2.1"},
            "runtime_manifest_path": str(PREFIX / "runtime-manifest.json"),
            "runtime_manifest_sha256": runtime_manifest_sha256,
            "global_library_environment": {
                "LD_LIBRARY_PATH": "/opt/deps/lib:/opt/colmap-pr8/lib"
            },
        },
    }


def validate_contract(contract, runtime_manifest_sha256):
    expected = make_contract(
        expected_native_contract(COLMAP_SHA), {}, runtime_manifest_sha256
    )
    if type(contract.get("schema_version")) is not int or json.dumps(
        contract, sort_keys=True
    ) != json.dumps(expected, sort_keys=True):
        raise ValueError(
            "derived image contract differs from exact shared runtime/native contract"
        )


def native_projection(contract):
    validate_contract(contract, contract["python"]["runtime_manifest_sha256"])
    return {
        k: (1 if k == "schema_version" else contract[k])
        for k in expected_native_contract(COLMAP_SHA)
    }


def verify_python(directory):
    directory = Path(directory)
    contract = json.loads((directory / "image-contract.json").read_text())
    validate_contract(contract, sha256(directory / "runtime-manifest.json"))
    validate_runtime(
        json.loads((directory / "runtime-manifest.json").read_text()),
        load_lock(directory / "environment-lock.json"),
    )
    verify_native(directory, native_projection(contract))
    print("PASS: schema2 shared Python, exact lock and unchanged native projection")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    verify_python(parser.parse_args().directory)
