"""Fail closed on per-object, per-entry MVS sm89 SASS / compute90 PTX coverage.

PTX spells the virtual compute_90 target as `.target sm_90`; an ELF listing
alone cannot establish PTX presence. Raw cuobjdump outputs are retained separately.
"""

import json
from pathlib import Path
import re
import sys


def verify(sass, ptx, patch_match=False):
    arches = set(re.findall(r"(?:arch\s*=\s*|code for\s+)sm_(\d+)", sass))
    if arches != {"89"}:
        raise ValueError(f"Expected filtered sm89 SASS, found {sorted(arches)}")
    native = set(re.findall(r"Function\s*:\s*(\S+)", sass))
    virtual = set()
    for section in re.split(r"(?=^\s*\.version\s)", ptx, flags=re.M):
        targets = re.findall(r"^\s*\.target\s+sm_(\d+)", section, re.M)
        if targets == ["90"]:
            virtual.update(re.findall(r"\.entry\s+([^\s(]+)\s*\(", section))
    if not native or not virtual:
        raise ValueError("Missing native sm89 functions or compute90 PTX entries")
    if native != virtual:
        raise ValueError(
            f"Kernel coverage mismatch: SASS-only={sorted(native - virtual)}, PTX-only={sorted(virtual - native)}"
        )
    if patch_match:
        for family in ("SweepFromTopToBottom", "ComputeInitialCost", "InitNormalMap"):
            if not any(family in name for name in native):
                raise ValueError(
                    f"Missing required patch-match kernel family: {family}"
                )
    return sorted(native)


def main(directory):
    directory = Path(directory)
    objects = json.loads((directory / "mvs-objects.json").read_text())
    expected = {"patch_match_cuda.cu.o", "gpu_mat_prng.cu.o", "gpu_mat_ref_image.cu.o"}
    if len(objects) != len(expected) or {Path(p).name for p in objects} != expected:
        raise ValueError("Expected exactly the three CUDA objects of colmap_mvs_cuda")
    for index, path in enumerate(objects):
        kernels = verify(
            (directory / f"mvs-{index}.sass.txt").read_text(),
            (directory / f"mvs-{index}.ptx.txt").read_text(),
            Path(path).name == "patch_match_cuda.cu.o",
        )
        for kernel in kernels:
            print(f"PASS {path}: {kernel}: sm_89 SASS + compute_90 PTX")
    print(
        "PASS: all emitted MVS kernel entries matched per object; GPU execution/JIT NOT tested"
    )


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except (ValueError, OSError) as error:
        sys.exit(f"FAIL: {error}")
