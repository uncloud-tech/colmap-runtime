"""Bind the PR8 image contract to independent binary, CLI and default evidence."""

import json
from pathlib import Path
import re
import sys


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


if __name__ == "__main__":
    try:
        verify(sys.argv[1])
    except (ValueError, OSError, TypeError) as error:
        sys.exit(f"FAIL: {error}")
