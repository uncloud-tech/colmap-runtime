"""Bind the PR8 image contract to independent binary, CLI and default evidence.

Also carries an ADDITIVE validator for the R570 dev image
(``dev/Dockerfile.r570``): when a directory contains ``manifest.json`` the
R570 path is used; otherwise the original PR8 path is byte-for-byte unchanged.
"""

import importlib.util
import json
from pathlib import Path
import re
import sys


def _load_r570_validator():
    path = Path(__file__).with_name("check_dev_r570_manifest.py")
    spec = importlib.util.spec_from_file_location("check_dev_r570_manifest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(directory):
    directory = Path(directory)
    contract = json.loads((directory / "image-contract.json").read_text())
    binary_record = (directory / "binary-sha256.txt").read_text()
    match = re.fullmatch(r"([0-9a-f]{64})  /opt/colmap-pr8/bin/colmap\n", binary_record)
    if not match:
        raise ValueError("Invalid installed binary hash evidence")
    binary_sha = match.group(1)
    expected = {
        "schema_version": 1,
        "source_repo": "https://github.com/uncloud-tech/colmap",
        "source_commit": "340f78310590cefda7cd3bb61ff0775ae5e2b59f",
        "source_tarball_sha256": "350f219ff4c07f68a9a834e0838d280d1a7f45884e0aa97182229401fe58695e",
        "binary_path": "/opt/colmap-pr8/bin/colmap",
        "binary_sha256": binary_sha,
        "cuda_architectures": "89-real;120-real",
        "mvs_cuda_architectures": "89-real;90-virtual",
        "mvs_codegen_policy": "upstream_blackwell_ptx_workaround",
        "gpu_execution_validated": False,
        "byte_exactness_inherited": False,
        "required_gpu_validation": "fresh_reference_map_gate",
        "sweep_tile_option": "--PatchMatchStereo.sweep_tile",
        "sweep_tile_values": [0, 8, 16, 32],
        "compact_prng_default": "0",
    }
    if contract != expected:
        raise ValueError("Baked image contract does not match PR8/binary evidence")
    manifest = (directory / "BUILD-MANIFEST.txt").read_text().splitlines()
    for key in (
        "source_commit",
        "binary_sha256",
        "cuda_architectures",
        "mvs_cuda_architectures",
        "mvs_codegen_policy",
        "gpu_execution_validated",
        "byte_exactness_inherited",
        "required_gpu_validation",
    ):
        value = expected[key]
        if isinstance(value, bool):
            value = json.dumps(value)
        entries = [line for line in manifest if line.startswith(f"{key}=")]
        if not entries or any(line != f"{key}={value}" for line in entries):
            raise ValueError(f"Manifest disagrees with contract: {key}")
    if (
        "--PatchMatchStereo.sweep_tile"
        not in (directory / "patch-match-help.txt").read_text()
    ):
        raise ValueError("Installed CLI does not expose runtime sweep_tile")
    defaults = (directory / "runtime-defaults.txt").read_text()
    if defaults != (
        "COLMAP_PATCH_MATCH_COMPACT_PRNG=0\ncolmap=/opt/colmap-pr8/bin/colmap\n"
    ):
        raise ValueError("Image defaults enable compact PRNG or select a stale binary")
    print(f"PASS: PR8 baked binary {binary_sha}; runtime sweep_tile; compact PRNG off")


def verify_r570(directory):
    """Validate the R570 manifest plus its contract-compatible BUILD-MANIFEST.txt."""
    directory = Path(directory)
    validator = _load_r570_validator()
    manifest = json.loads((directory / "manifest.json").read_text())
    validator.validate_manifest(manifest)
    fields = {}
    for line in (directory / "BUILD-MANIFEST.txt").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    controls = manifest["controls"]
    expected = {
        "source_commit": manifest["identity"]["source_commit"],
        "source_archive_sha256": manifest["identity"]["source_archive_sha256"],
        "seed_patch_sha256": manifest["seed_overlay"]["patch_sha256"],
        "binary_path": controls["stock"]["path"],
        "binary_sha256": controls["stock"]["sha256"],
        "seed_binary_path": controls["seed"]["path"],
        "seed_binary_sha256": controls["seed"]["sha256"],
        "cuda_architectures": manifest["build"]["cuda_architectures"],
        "mvs_codegen_policy": manifest["mvs_evidence"]["policy"],
        "gpu_execution_validated": "false",
        "required_gpu_validation": manifest["gpu"]["required_gpu_validation"],
        "environment_lock_sha256": manifest["python"]["environment_lock_sha256"],
        "validator_version": str(manifest["validator_version"]),
        "readiness_command": manifest["readiness"]["command"],
    }
    for key, value in expected.items():
        if fields.get(key) != value:
            raise ValueError(f"R570 BUILD-MANIFEST.txt disagrees with manifest: {key}")
    print(
        "PASS: R570 manifest binds stock "
        f"{controls['stock']['sha256'][:12]} and seed {controls['seed']['sha256'][:12]}; "
        "contract-compatible BUILD-MANIFEST.txt; no image self-identity"
    )


if __name__ == "__main__":
    try:
        directory = Path(sys.argv[1])
        if (directory / "manifest.json").is_file():
            verify_r570(directory)
        else:
            verify(directory)
    except (ValueError, OSError, TypeError) as error:
        sys.exit(f"FAIL: {error}")
