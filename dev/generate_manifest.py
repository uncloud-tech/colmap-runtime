#!/usr/bin/env python3
"""Generate and validate the baked R570 dev-image manifest.

The manifest records PAYLOAD identities only: base image digest, source
commit/tree + archive hash, seed-overlay bytes, both named control binaries,
toolchain, dependency pins and the locked Python closure.  It never records the
image's own final OCI digest/imageID - that is host-wrapped with
``docker inspect`` imageID + the requested registry digest.

Pure helpers (``build_manifest``, ``parse_*``) are unit-tested against fixtures;
``collect_facts`` reads the real build evidence produced inside the image.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _candidate in (HERE, HERE.parent / "scripts"):
    if (_candidate / "check_dev_r570_manifest.py").is_file():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break
import check_dev_r570_manifest as VALIDATOR  # noqa: E402

EVIDENCE_ROOT = Path("/opt/photogram-dev/evidence")
MVS_OBJECT_NAMES = ("patch_match_cuda", "gpu_mat_prng", "gpu_mat_ref_image")
# Deployed harness payload whose exact bytes must be verifiable from the
# manifest ("verify what is deployed").  Absolute in-image paths.
HARNESS_FILES = VALIDATOR.HARNESS_FILES
APT_UTILITY_PACKAGES = (
    "ca-certificates", "curl", "git", "cmake", "ninja-build", "pkg-config",
    "gnupg", "xz-utils", "file", "unzip", "lsb-release", "procps", "time",
    "jq", "pciutils", "gzip",
)


def parse_sha256_file(text):
    """First field of a ``sha256sum`` output file."""
    first = text.strip().splitlines()[0].split()
    if not first or not VALIDATOR.HEX64.match(first[0]):
        raise ValueError("not a sha256sum record")
    return first[0]


def arches_from_listing(text, kind):
    """Map a raw ``cuobjdump --list-elf/--list-ptx`` dump to architecture names.

    PTX files spell the virtual target as ``.sm_90``; semantically that is the
    ``compute_90`` PTX family, so it is labelled accordingly.
    """
    values = sorted({int(v) for v in re.findall(r"sm_(\d+)", text)})
    if kind == "elf":
        return [f"sm_{v}" for v in values]
    if kind == "ptx":
        return [f"compute_{v}" for v in values]
    raise ValueError(f"unknown listing kind: {kind}")


def parse_requirements(text):
    packages = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split(" --hash=", 1)[0]
        if "==@" in name:
            name = name.replace("==@", "@")
        packages.append(name)
    return packages


def parse_key_values(text):
    fields = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
    return fields


def _evidence(root, name):
    return Path(root) / name


def collect_facts(root=EVIDENCE_ROOT, run=subprocess.run):
    root = Path(root)
    facts = {"controls": {}, "mvs": {}}

    facts["source_archive_sha256"] = parse_sha256_file(
        _evidence(root, "source-archive.sha256").read_text()
    )
    # Hash the harness as actually deployed inside the image (not the build
    # context) so a stale/edited script is caught by the manifest.
    facts["harness_files"] = {
        name: VALIDATOR.sha256_hex(Path(name).read_bytes()) for name in HARNESS_FILES
    }
    for name in ("stock", "seed"):
        arm = _evidence(root, name)
        facts["controls"][name] = {
            "sha256": parse_sha256_file((arm / "binary.sha256").read_text()),
            "help_sha256": parse_sha256_file((arm / "help.sha256").read_text()),
            "version_cc_sha256": parse_sha256_file((arm / "version-cc.sha256").read_text()),
        }
        elf = sorted(
            {
                arch
                for object_name in MVS_OBJECT_NAMES
                for arch in arches_from_listing(
                    (arm / "mvs" / f"{object_name}.elf.txt").read_text(), "elf"
                )
            }
        )
        ptx = sorted(
            {
                arch
                for object_name in MVS_OBJECT_NAMES
                for arch in arches_from_listing(
                    (arm / "mvs" / f"{object_name}.ptx.txt").read_text(), "ptx"
                )
            }
        )
        facts["mvs"][name] = {
            "observed_elf": elf,
            "observed_ptx": ptx,
            "native_sm120": "sm_120" in elf,
            "objects": {
                object_name: {
                    "elf": arches_from_listing(
                        (arm / "mvs" / f"{object_name}.elf.txt").read_text(), "elf"
                    ),
                    "ptx": arches_from_listing(
                        (arm / "mvs" / f"{object_name}.ptx.txt").read_text(), "ptx"
                    ),
                }
                for object_name in MVS_OBJECT_NAMES
            },
        }
    facts["build"] = {
        "install_library_targets": [
            line.strip()
            for line in _evidence(root, "install-library-targets.txt").read_text().splitlines()
            if line.strip()
        ]
    }
    toolchain = parse_key_values((root / "toolchain.txt").read_text())
    facts["toolchain"] = {
        key: toolchain[key]
        for key in ("nvcc", "cuda", "gcc", "cmake", "ninja", "python")
    }
    facts["python_packages"] = parse_requirements(
        (_evidence(root, "python-requirements.lock").read_text())
    )
    apt_lines = run(
        ["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], capture_output=True, text=True
    ).stdout
    versions = dict(
        line.split("\t", 1) for line in apt_lines.splitlines() if "\t" in line
    )
    facts["apt_versions"] = {
        package: versions.get(package, "unknown") for package in APT_UTILITY_PACKAGES
    }
    return facts


def build_manifest(facts):
    """Compose the full manifest from collected facts and the pinned constants."""
    manifest = {
        "schema_version": VALIDATOR.SCHEMA_VERSION,
        "validator_version": VALIDATOR.VALIDATOR_VERSION,
        "image": "colmap-dev-r570",
        "identity": {
            "base_image": VALIDATOR.BASE_IMAGE,
            "source_repo": VALIDATOR.SOURCE_REPO,
            "source_commit": VALIDATOR.SOURCE_COMMIT,
            "source_tree": VALIDATOR.SOURCE_TREE,
            "source_archive_sha256": facts["source_archive_sha256"],
        },
        "seed_overlay": {
            "patch_path": "/opt/photogram-dev/patches/seed-minimal-d7ffb9c.patch",
            "patch_sha256": VALIDATOR.SEED_PATCH_SHA256,
            "base_commit": VALIDATOR.SOURCE_COMMIT,
        },
        "controls": {
            name: {
                "path": VALIDATOR.CONTROL_PATHS[name],
                "install_prefix": VALIDATOR.CONTROL_PREFIXES[name],
                "source_dir": f"/opt/src/colmap-{name}",
                "sha256": facts["controls"][name]["sha256"],
                "help_path": f"/opt/photogram-dev/evidence/{name}/help.txt",
                "help_sha256": facts["controls"][name]["help_sha256"],
                "version_cc_sha256": facts["controls"][name]["version_cc_sha256"],
                "overlay": "none" if name == "stock" else "seed-minimal-d7ffb9c",
            }
            for name in VALIDATOR.CONTROL_PATHS
        },
        "harness_files": dict(facts["harness_files"]),
        "toolchain": {
            "nvcc": facts["toolchain"]["nvcc"],
            "cuda": facts["toolchain"]["cuda"],
            "gcc": facts["toolchain"]["gcc"],
            "cmake": facts["toolchain"]["cmake"],
            "ninja": facts["toolchain"]["ninja"],
            "boost": VALIDATOR.DEP_PINS["boost"][0],
            "poselib": VALIDATOR.DEP_PINS["poselib"][0],
            "faiss": VALIDATOR.DEP_PINS["faiss"][0],
            "gtest": VALIDATOR.DEP_PINS["gtest"][0],
            "python": facts["toolchain"]["python"],
        },
        "dependencies": {
            "prefix": "/opt/deps",
            "pins": {
                name: {"version": version, "sha256": digest}
                for name, (version, digest) in VALIDATOR.DEP_PINS.items()
            },
        },
        "build": {
            "build_type": "Release",
            "cuda_enabled": True,
            "mvs_enabled": True,
            "gui_enabled": False,
            "opengl_enabled": False,
            "onnx_enabled": False,
            "tests_enabled": True,
            "build_shared_libs": False,
            "fetch_all": False,
            "ccache_enabled": False,
            "prefix_path": "/opt/deps",
            "cuda_architectures": VALIDATOR.CUDA_ARCHITECTURES,
            "cmake_cuda_architectures": VALIDATOR.CUDA_ARCHITECTURES,
            "executable_target": "colmap_main",
            "mvs_test_targets": list(VALIDATOR.MVS_TEST_TARGETS),
            "install_library_targets": sorted(facts["build"]["install_library_targets"]),
        },
        "mvs_evidence": {
            "policy": "upstream_blackwell_ptx_workaround_preserved",
            "sm120_source_toggle_patch": False,
            "objects": list(VALIDATOR.MVS_OBJECTS),
            "per_control": {
                name: {
                    "observed_elf": facts["mvs"][name]["observed_elf"],
                    "observed_ptx": facts["mvs"][name]["observed_ptx"],
                    "native_sm120": facts["mvs"][name]["native_sm120"],
                    "objects": facts["mvs"][name]["objects"],
                    "evidence_dir": f"/opt/photogram-dev/evidence/{name}/mvs",
                }
                for name in VALIDATOR.CONTROL_PATHS
            },
        },
        "python": {
            "prefix": VALIDATOR.PYTHON_PREFIX,
            "interpreter": VALIDATOR.PYTHON_INTERPRETER,
            "pip": VALIDATOR.PYTHON_PIP,
            "environment_lock_sha256": VALIDATOR.ENVIRONMENT_LOCK_SHA256,
            "packages": sorted(facts["python_packages"]),
            "native_loader_cuda129": False,
        },
        "utilities": {"apt_versions": facts["apt_versions"]},
        "gpu": {
            "documented_min_driver": VALIDATOR.DOCUMENTED_MIN_DRIVER,
            "documented_min_driver_url": VALIDATOR.DOCUMENTED_MIN_DRIVER_URL,
            "policy_min_driver": VALIDATOR.POLICY_MIN_DRIVER,
            "tested_driver": VALIDATOR.TESTED_DRIVER,
            "tested_driver_evidence": "docs/evidence/2026-10-08-task0-builder-acceptance.md",
            "tested_driver_status": "prior_image_experience_not_new_image_qualification",
            "required_gpu_validation": VALIDATOR.REQUIRED_GPU_VALIDATION,
            "gpu_execution_validated": False,
        },
        "readiness": {
            "command": VALIDATOR.READINESS_COMMAND,
            "gpu_command": VALIDATOR.GPU_SMOKE_COMMAND,
        },
        "prior_reference": {
            "note": "historical Task0 c6 arms on runtime-dev 8993096; NOT proof for this image",
            "stock_binary_sha256": "61b943e456e8930a43b71ca941593917dde45289df3ff564850a4ef66148a99a",
            "seed_binary_sha256": "db677ff94ecfbf3585697398c9f0ceb46b55c3444c69ba0ae8cdc5c7058b9e72",
        },
    }
    VALIDATOR.validate_manifest(manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default=str(EVIDENCE_ROOT))
    parser.add_argument("--out", default="/opt/photogram-dev/manifest.json")
    args = parser.parse_args(argv)
    manifest = build_manifest(collect_facts(args.evidence))
    Path(args.out).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(
        "wrote "
        f"{args.out} evidence_identity={VALIDATOR.evidence_identity(manifest)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
