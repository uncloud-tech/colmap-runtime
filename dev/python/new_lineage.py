"""New-lineage assembly: runtime-only snapshot -> observed evidence -> schema-3 bake.

The historical bake path (``collect_dev_python_native.sh`` + ``verify_runtime
--bake``) requires the prebuilt source scaffold (``/opt/src``,
``/opt/colmap-dev/image-contract.json``) and validates the OLD binary/environment,
so it cannot assemble the layer-derived lineage. This module is the NEW-LINEAGE
entrypoint: it snapshots the runtime-only base+layer parent, validates the
OBSERVED native bytes/architecture/environment against the hash-bound record, and
produces the schema-3 contract + in-image lock. The historical path is untouched.
"""

import argparse
import json
from pathlib import Path
import sys

from dev.layer_binding import (
    expected_native_env,
    resolve_parent_reference,
)
from dev.layer_identity import parse_build_manifest
from dev.python.locked_env import PREFIX, load_lock, sha256
from dev.python.verify_runtime import (
    collect_runtime,
    file_inventory,
    read_native_snapshot,
)
from scripts.check_layer_image_contract import build_contract_from_record

OBSERVED_SOURCE = "runtime-layer-snapshot"
REQUIRED_OBSERVED = (
    "binary-sha256.txt",
    "native-env.txt",
    "native-library-resolution.txt",
    "BUILD-MANIFEST.txt",
)


class NewLineageError(ValueError):
    """The runtime-only snapshot cannot be bound to the derived record."""


def collect_observed(snapshot_dir):
    """Read the ACTUAL observed native evidence from the runtime parent snapshot."""
    directory = Path(snapshot_dir)
    for name in REQUIRED_OBSERVED:
        if not (directory / name).is_file():
            raise NewLineageError(f"runtime snapshot is missing {name}")
    binary = (directory / "binary-sha256.txt").read_text().split()
    if len(binary) != 2 or binary[1] != "/opt/colmap-pr8/bin/colmap":
        raise NewLineageError("binary-sha256.txt is not an observed binary hash")
    fields, _ = parse_build_manifest((directory / "BUILD-MANIFEST.txt").read_text())
    resolution = (directory / "native-library-resolution.txt").read_text()
    return {
        "schema_version": 1,
        "source": OBSERVED_SOURCE,
        "binary_sha256": binary[0],
        "cuda_architectures": fields.get("cuda_architectures"),
        "mvs_cuda_architectures": fields.get("mvs_cuda_architectures"),
        "native_env": (directory / "native-env.txt").read_text(),
        "library_resolution": "unresolved" if "not found" in resolution else "resolved",
    }


def validate_observed(observed, record):
    """Bind the observed bytes/arch/environment to the hash-bound record."""
    if observed.get("binary_sha256") != record.get("binary_sha256"):
        raise NewLineageError("observed native binary does not match the record")
    for key in ("cuda_architectures", "mvs_cuda_architectures"):
        if observed.get(key) != record.get(key):
            raise NewLineageError(f"observed {key} does not match the record")
    if observed.get("native_env") != expected_native_env(record):
        raise NewLineageError("observed native environment does not match the record")
    if observed.get("library_resolution") != "resolved":
        raise NewLineageError("observed native libraries did not all resolve")
    return observed


def _coerce_path(value, name):
    """The bake argv supplies strings; the snapshot reader needs Path objects.

    A non-path argument is refused with a named error rather than surfacing as an
    opaque ``TypeError`` (the round-1 verification defect).
    """
    if not isinstance(value, (str, Path)):
        raise NewLineageError(
            f"{name} must be a path-like string, not {type(value).__name__}"
        )
    if not str(value):
        raise NewLineageError(f"{name} must be a non-empty path")
    return Path(value)


def bake(
    record_path,
    before,
    after,
    scratch,
    out_manifest,
    out_observed,
    out_contract,
    python_native_libs=None,
):
    record_path = _coerce_path(record_path, "record")
    before = _coerce_path(before, "before")
    after = _coerce_path(after, "after")
    scratch = _coerce_path(scratch, "scratch")
    out_manifest = _coerce_path(out_manifest, "out-manifest")
    out_observed = _coerce_path(out_observed, "out-observed")
    out_contract = _coerce_path(out_contract, "out-contract")
    if python_native_libs is not None:
        python_native_libs = _coerce_path(python_native_libs, "python-native-libs")
    record = json.loads(record_path.read_text())
    # The parent must be a published, digest-pinned reference (never a config id).
    resolve_parent_reference(record)
    observed = validate_observed(collect_observed(after), record)
    if python_native_libs is not None:
        if not python_native_libs.is_file():
            raise NewLineageError(
                f"python native-libs closure is missing: {python_native_libs}"
            )
        observed["python_native_libs_sha256"] = sha256(python_native_libs)
    out_observed.write_text(json.dumps(observed, indent=2, sort_keys=True) + "\n")
    lock = load_lock(PREFIX / "environment-lock.json")
    evidence = collect_runtime(
        PREFIX,
        lock,
        scratch,
        read_native_snapshot(before),
        read_native_snapshot(after),
        native_env=expected_native_env(record),
        binary_sha=record["binary_sha256"],
    )
    evidence["installed_files"] = file_inventory(PREFIX)
    out_manifest.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    contract = build_contract_from_record(record, sha256(out_manifest))
    out_contract.write_text(json.dumps(contract, sort_keys=True, indent=2) + "\n")
    print(
        "PASS: new-lineage bake bound observed native evidence and wrote the "
        "schema-3 contract"
    )
    return contract


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    bake_parser = sub.add_parser("bake")
    bake_parser.add_argument("--record", required=True)
    bake_parser.add_argument("--before", required=True)
    bake_parser.add_argument("--after", required=True)
    bake_parser.add_argument("--scratch", required=True)
    bake_parser.add_argument("--out-manifest", required=True)
    bake_parser.add_argument("--out-observed", required=True)
    bake_parser.add_argument("--out-contract", required=True)
    bake_parser.add_argument("--python-native-libs")
    args = parser.parse_args(argv)
    try:
        bake(
            args.record,
            args.before,
            args.after,
            args.scratch,
            args.out_manifest,
            args.out_observed,
            args.out_contract,
            python_native_libs=args.python_native_libs,
        )
    except (NewLineageError, OSError, ValueError) as error:
        sys.exit(f"FAIL: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
