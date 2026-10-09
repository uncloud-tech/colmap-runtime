"""Independent contract for the R570.195.03 / CUDA 12.8 dev-image manifest.

The image bakes ``/opt/photogram-dev/manifest.json`` with the *payload*
identities only (base image, source commit/tree, seed overlay bytes, control
binaries, toolchain and the locked Python closure).  It deliberately does NOT
contain its own final OCI digest / imageID: that value depends on the manifest
itself and is therefore circular.  A host-side caller wraps the report with
``docker inspect`` imageID plus the requested registry digest.

This module is the *independent* reader: it never trusts the in-image writer
and fails closed on any drift from the commissioned identities.  It also
validates the runtime doctor/gpu-smoke reports, whose readiness semantics are:

* ``cpu_ready`` alone is never ``ready``;
* ``gpu_status`` is ``not_checked`` unless an explicit ``gpu-smoke`` ran;
* ``validator_version`` + ``evidence_identity`` prevent a cached GPU
  qualification from being reused after any payload input changes.
"""

import hashlib
import json
import re
import sys

SCHEMA_VERSION = 1
VALIDATOR_VERSION = "1"

BASE_IMAGE = (
    "nvidia/cuda:12.8.1-devel-ubuntu24.04@"
    "sha256:4b9ed5fa8361736996499f64ecebf25d4ec37ff56e4d11323ccde10aa36e0c43"
)
SOURCE_REPO = "https://github.com/uncloud-tech/colmap"
# Canonical c6 development base. Corroborated by the Task0 builder receipt and
# every repository artifact; the task brief's trailing "b98" is a transcription
# error (the accepted tree hash below only exists for ...b76).
SOURCE_COMMIT = "c6ab4f897c94f10b15bdecc442dcfce4688f1b76"
SOURCE_TREE = "5488323854cd99a7d785ada78e4106cb44e3c518"
SEED_PATCH_SHA256 = (
    "d6fe7c609b18714940aa1d0b7c56318fda2fe8b809d4d4e20d2ced9dd3b7651e"
)
ENVIRONMENT_LOCK_SHA256 = (
    "a22ac04ee8febc9f46f281d7b01d200e73e75f2d380bbc02b0bffc4992ee45cd"
)
CONTROL_PATHS = {
    "stock": "/opt/colmap-stock/bin/colmap",
    "seed": "/opt/colmap-seed/bin/colmap",
}
CONTROL_PREFIXES = {
    "stock": "/opt/colmap-stock",
    "seed": "/opt/colmap-seed",
}
DEP_PINS = {
    "boost": ("1.92.0", "9bed76128d4e46755dbe818487788c6fceb6f72b378f4daa49b7e1e600d9088d"),
    "poselib": ("1bb8881f08e68f0b3d9b2ecc411fc15e7766ef1b", "ee46322581c7901fe24e91434eeec27163f820d481cba5faa43d37651fabc8e8"),
    "faiss": ("1.14.1", "4b1ae7e7a0a46385b4084f0e3945623a15fcf99d793bf44d82aae8e24f11e5f5"),
    "gtest": ("063de7e9578f82b369302001269680b4b1553359", "623fe05d283020f37a579a8985ba338091ac7229da62b5591ff40acdf05b95e2"),
}
CUDA_ARCHITECTURES = "86-real;89-real;120-real;70-virtual"
MVS_OBJECTS = ["patch_match_cuda.cu.o", "gpu_mat_prng.cu.o", "gpu_mat_ref_image.cu.o"]
MVS_OBJECT_STEMS = [name[:-5] for name in MVS_OBJECTS]
MVS_TEST_TARGETS = [
    "colmap_mvs_depth_map_test",
    "colmap_mvs_normal_map_test",
    "colmap_mvs_mat_test",
]
DOCUMENTED_MIN_DRIVER = "570.26"
DOCUMENTED_MIN_DRIVER_URL = (
    "https://docs.nvidia.com/cuda/archive/12.8.1/cuda-toolkit-release-notes/"
    "index.html#cuda-driver"
)
POLICY_MIN_DRIVER = "570.195.03"
TESTED_DRIVER = "570.195.03"
REQUIRED_GPU_VALIDATION = "fresh_reference_map_gate"
PYTHON_PREFIX = "/opt/colmap-python"
PYTHON_INTERPRETER = "3.14.7"
PYTHON_PIP = "26.2.1"
PYTHON_PACKAGE_COUNT = 16
# Deployed harness payload: its exact bytes must be verifiable from the manifest.
HARNESS_ROOT = "/opt/photogram-dev"
HARNESS_FILES = (
    f"{HARNESS_ROOT}/photogram_dev.py",
    f"{HARNESS_ROOT}/entrypoint.r570.sh",
    f"{HARNESS_ROOT}/check_dev_r570_manifest.py",
    f"{HARNESS_ROOT}/build-control.sh",
    f"{HARNESS_ROOT}/gpu-probe/cuda_launch.cu",
    f"{HARNESS_ROOT}/gpu-probe/driver_resolve.c",
)
READINESS_COMMAND = "photogram-dev doctor"
GPU_SMOKE_COMMAND = "photogram-dev gpu-smoke"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
# A baked manifest must never carry the image's own final identity (circular).
FORBIDDEN_IDENTITY_KEYS = {"image_digest", "image_id", "imageid", "oci_digest", "config_digest"}
GPU_STATUS_VALUES = {"passed", "failed", "not_checked"}


class ContractError(ValueError):
    """The manifest or a runtime report violates the commissioned contract."""


def sha256_hex(data):
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def assert_no_self_identity(node, path="$"):
    """Reject any key that would embed the manifest's own final OCI identity."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key.strip().lower() in FORBIDDEN_IDENTITY_KEYS:
                raise ContractError(f"baked manifest embeds its own image identity at {path}.{key}")
            assert_no_self_identity(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            assert_no_self_identity(value, f"{path}[{index}]")


def _require_hex(value, field):
    if not isinstance(value, str) or not HEX64.match(value):
        raise ContractError(f"{field} must be a lowercase sha256")


def evidence_identity(manifest):
    """Hash the payload inputs that must invalidate a stale GPU qualification."""
    payload = {
        "base_image": manifest["identity"]["base_image"],
        "source_commit": manifest["identity"]["source_commit"],
        "source_tree": manifest["identity"]["source_tree"],
        "seed_patch_sha256": manifest["seed_overlay"]["patch_sha256"],
        "toolchain": manifest["toolchain"],
        "controls": {
            name: manifest["controls"][name]["sha256"] for name in CONTROL_PATHS
        },
        "python_lock_sha256": manifest["python"]["environment_lock_sha256"],
        "cuda_architectures": manifest["build"]["cuda_architectures"],
    }
    return sha256_hex(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ContractError("manifest must be a JSON object")
    assert_no_self_identity(manifest)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("schema_version must be 1")
    if manifest.get("validator_version") != VALIDATOR_VERSION:
        raise ContractError("validator_version mismatch")

    identity = manifest["identity"]
    if identity["base_image"] != BASE_IMAGE:
        raise ContractError("base image digest is not the commissioned 12.8.1 pin")
    if identity["source_repo"] != SOURCE_REPO:
        raise ContractError("source_repo mismatch")
    if identity["source_commit"] != SOURCE_COMMIT:
        raise ContractError("source_commit mismatch")
    if identity["source_tree"] != SOURCE_TREE:
        raise ContractError("source_tree mismatch")
    _require_hex(identity["source_archive_sha256"], "identity.source_archive_sha256")

    overlay = manifest["seed_overlay"]
    if overlay["patch_sha256"] != SEED_PATCH_SHA256:
        raise ContractError("seed overlay patch hash mismatch")
    if overlay["patch_path"] != "/opt/photogram-dev/patches/seed-minimal-d7ffb9c.patch":
        raise ContractError("seed overlay patch path mismatch")
    if overlay["base_commit"] != SOURCE_COMMIT:
        raise ContractError("seed overlay base_commit mismatch")

    controls = manifest["controls"]
    if set(controls) != set(CONTROL_PATHS):
        raise ContractError("controls must be exactly stock and seed")
    for name, expected_path in CONTROL_PATHS.items():
        control = controls[name]
        if control["path"] != expected_path:
            raise ContractError(f"{name} control path mismatch")
        if control["install_prefix"] != CONTROL_PREFIXES[name]:
            raise ContractError(f"{name} install prefix mismatch")
        _require_hex(control["sha256"], f"controls.{name}.sha256")
        _require_hex(control["help_sha256"], f"controls.{name}.help_sha256")
        _require_hex(control["version_cc_sha256"], f"controls.{name}.version_cc_sha256")
    if controls["stock"]["overlay"] != "none":
        raise ContractError("stock control must be pristine (no overlay)")
    if controls["seed"]["overlay"] != "seed-minimal-d7ffb9c":
        raise ContractError("seed control overlay identity mismatch")

    toolchain = manifest["toolchain"]
    for key in ("nvcc", "gcc", "cmake", "ninja", "boost", "poselib", "faiss", "gtest", "python"):
        if not toolchain.get(key):
            raise ContractError(f"toolchain.{key} is required")
    if toolchain["boost"] != DEP_PINS["boost"][0]:
        raise ContractError("boost version drift")
    if toolchain["poselib"] != DEP_PINS["poselib"][0]:
        raise ContractError("poselib pin drift")
    if toolchain["faiss"] != DEP_PINS["faiss"][0]:
        raise ContractError("faiss version drift")
    if toolchain["gtest"] != DEP_PINS["gtest"][0]:
        raise ContractError("gtest pin drift")

    pins = manifest["dependencies"]["pins"]
    for name, (version, digest) in DEP_PINS.items():
        if pins[name]["version"] != version:
            raise ContractError(f"dependency pin {name} version drift")
        if pins[name]["sha256"] != digest:
            raise ContractError(f"dependency pin {name} hash drift")
    if manifest["dependencies"]["prefix"] != "/opt/deps":
        raise ContractError("shared dependency prefix must be /opt/deps")

    build = manifest["build"]
    if build["cuda_architectures"] != CUDA_ARCHITECTURES:
        raise ContractError("CUDA architecture list drift")
    for flag in ("gui_enabled", "opengl_enabled", "onnx_enabled", "fetch_all", "build_shared_libs"):
        if build[flag] is not False:
            raise ContractError(f"build.{flag} must be false")
    for flag in ("cuda_enabled", "mvs_enabled", "tests_enabled"):
        if build[flag] is not True:
            raise ContractError(f"build.{flag} must be true")
    if build["build_type"] != "Release":
        raise ContractError("build_type must be Release")
    if build["prefix_path"] != "/opt/deps":
        raise ContractError("CMAKE_PREFIX_PATH must be /opt/deps")
    if build["executable_target"] != "colmap_main":
        raise ContractError("executable target must be colmap_main")
    if build["mvs_test_targets"] != MVS_TEST_TARGETS:
        raise ContractError("MVS test target set drift")
    if not build["install_library_targets"]:
        raise ContractError("install-required library targets must be recorded")

    mvs = manifest["mvs_evidence"]
    if mvs["policy"] != "upstream_blackwell_ptx_workaround_preserved":
        raise ContractError("MVS PTX workaround policy must be preserved")
    if mvs["sm120_source_toggle_patch"] is not False:
        raise ContractError("no sm_120 MVS source toggle patch may be present")
    if mvs["objects"] != MVS_OBJECTS:
        raise ContractError("MVS object set drift")
    for name in CONTROL_PATHS:
        per = mvs["per_control"][name]
        if per["observed_elf"] != ["sm_86", "sm_89"]:
            raise ContractError(f"{name} observed ELF drift: {per['observed_elf']}")
        if per["observed_ptx"] != ["compute_70", "compute_90"]:
            raise ContractError(f"{name} observed PTX drift: {per['observed_ptx']}")
        if per["native_sm120"] is not False:
            raise ContractError(f"{name} must not emit native sm_120 MVS SASS")
        objects = per["objects"]
        if set(objects) != set(MVS_OBJECT_STEMS):
            raise ContractError(f"{name} per-object MVS evidence set drift")
        for stem, record in objects.items():
            if not set(record["elf"]) <= {"sm_86", "sm_89"}:
                raise ContractError(f"{name}/{stem} emits unexpected MVS SASS: {record['elf']}")
            if "sm_120" in record["elf"]:
                raise ContractError(f"{name}/{stem} must not emit native sm_120 MVS SASS")
            if not set(record["ptx"]) <= {"compute_70", "compute_90"}:
                raise ContractError(f"{name}/{stem} emits unexpected MVS PTX: {record['ptx']}")

    gpu = manifest["gpu"]
    if gpu["documented_min_driver"] != DOCUMENTED_MIN_DRIVER:
        raise ContractError("documented CUDA 12.8.1 driver minimum mismatch")
    if gpu["documented_min_driver_url"] != DOCUMENTED_MIN_DRIVER_URL:
        raise ContractError("official driver-requirement URL mismatch")
    if gpu["policy_min_driver"] != POLICY_MIN_DRIVER:
        raise ContractError("policy driver minimum mismatch")
    if gpu["tested_driver"] != TESTED_DRIVER:
        raise ContractError("tested driver mismatch")
    if gpu["gpu_execution_validated"] is not False:
        raise ContractError("a freshly baked image cannot claim GPU execution")
    if gpu["required_gpu_validation"] != REQUIRED_GPU_VALIDATION:
        raise ContractError("required GPU validation gate mismatch")

    python = manifest["python"]
    if python["prefix"] != PYTHON_PREFIX:
        raise ContractError("python prefix mismatch")
    if python["interpreter"] != PYTHON_INTERPRETER or python["pip"] != PYTHON_PIP:
        raise ContractError("python interpreter/pip identity mismatch")
    if python["environment_lock_sha256"] != ENVIRONMENT_LOCK_SHA256:
        raise ContractError("environment lock is not the byte-identical lock")
    if len(python["packages"]) != PYTHON_PACKAGE_COUNT:
        raise ContractError("expected the 16 locked Python packages")
    if python["native_loader_cuda129"] is not False:
        raise ContractError("CUDA 12.9 runtime must stay off the native loader path")

    if manifest["readiness"]["command"] != READINESS_COMMAND:
        raise ContractError("readiness command mismatch")
    if manifest["readiness"]["gpu_command"] != GPU_SMOKE_COMMAND:
        raise ContractError("gpu-smoke command mismatch")

    harness = manifest.get("harness_files")
    if not isinstance(harness, dict) or set(harness) != set(HARNESS_FILES):
        raise ContractError("harness_files must record exactly the deployed harness set")
    for name in HARNESS_FILES:
        _require_hex(harness[name], f"harness_files.{name}")
    return manifest


def validate_doctor_report(report):
    if not isinstance(report, dict):
        raise ContractError("doctor report must be a JSON object")
    assert_no_self_identity(report)
    if report.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("doctor schema_version must be 1")
    if report.get("validator_version") != VALIDATOR_VERSION:
        raise ContractError("doctor validator_version mismatch")
    if not isinstance(report.get("cpu_ready"), bool):
        raise ContractError("cpu_ready must be boolean")
    gpu_status = report.get("gpu_status")
    if gpu_status not in GPU_STATUS_VALUES:
        raise ContractError("gpu_status must be passed/failed/not_checked")
    if not isinstance(report.get("host_prerequisites"), dict):
        raise ContractError("host_prerequisites must be an object")
    _require_hex(report.get("evidence_identity", ""), "evidence_identity")
    expected_ready = (
        report["cpu_ready"]
        and gpu_status == "passed"
        and report["host_prerequisites"].get("ok") is True
    )
    if report.get("ready") is not expected_ready:
        raise ContractError("ready must require cpu_ready AND passed gpu AND host prerequisites")
    if report.get("command") == "doctor" and gpu_status != "not_checked":
        raise ContractError("the default doctor must report gpu_status=not_checked")
    return report


def main(argv):
    if len(argv) != 2:
        return "usage: check_dev_r570_manifest.py <manifest.json|report.json>"
    with open(argv[1]) as stream:
        payload = json.loads(stream.read())
    if "cpu_ready" in payload:
        validate_doctor_report(payload)
        print("PASS: doctor report satisfies the readiness contract")
    else:
        validate_manifest(payload)
        print(
            "PASS: baked manifest bound to "
            f"{payload['identity']['source_commit']} controls, "
            f"evidence_identity={evidence_identity(payload)}"
        )
    return 0


if __name__ == "__main__":
    try:
        result = main(sys.argv)
    except (ContractError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        sys.exit(f"FAIL: {error}")
    if isinstance(result, str):
        sys.exit(result)
