#!/usr/bin/env python3
"""photogram-dev: offline readiness doctor and explicit GPU smoke for the R570 image.

Design contract (see ``scripts/check_dev_r570_manifest.py``):

* ``doctor`` is the DEFAULT, non-mutating, CPU/loader-only readiness check.  It
  reads the baked manifest, hashes BOTH named controls, invokes ``-h`` for each,
  follows the recursive loader closure and reports the workspace mount as
  *readable* only.  It never writes and it never claims GPU readiness:
  ``gpu_status`` stays ``not_checked``.
* ``prepare`` is the explicit workspace validation mode.  It is the ONLY mode
  that probes write access, and it creates and removes only its own probe
  directory.
* ``gpu-smoke`` is explicit and non-default.  Only it may set
  ``gpu_status=passed``.  It asserts the NVIDIA identity, resolves the real
  host ``libcuda.so.1`` (rejecting a Python-wheel stub), ``dlopen``/``cuInit``
  and runs an ``sm_86`` kernel whose 1024 distinct results are checked exactly.

Readiness is never inferred from CPU checks alone; a ``ready`` receipt requires
``cpu_ready`` AND ``gpu_status=passed`` AND satisfied host prerequisites.  Every
report carries ``validator_version`` and an ``evidence_identity`` so a cached
GPU qualification is invalidated by any changed payload input.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MANIFEST_PATH = Path("/opt/photogram-dev/manifest.json")
DEFAULT_WORKSPACE = "/work"

# Prohibited loader targets: the historical PR8 install prefix and any CUDA
# stub shipped inside a Python environment (must never satisfy the loader).
PROHIBITED_CLOSURE_MARKERS = (
    "/opt/colmap-pr8/",
    "/site-packages/",
    "/dist-packages/",
    "nvidia_cuda_runtime",
    "/nvidia/",
)


def _load_validator():
    """Import the independent validator from beside us or from ``scripts/``."""
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent / "scripts"):
        if (candidate / "check_dev_r570_manifest.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            import check_dev_r570_manifest as module

            return module
    raise SystemExit("FAIL: check_dev_r570_manifest.py not found next to photogram_dev.py")


VALIDATOR = _load_validator()


class Inspector:
    """Real filesystem/process access. Injected wholesale in unit tests."""

    def sha256(self, path):
        with open(path, "rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def read_text(self, path):
        return Path(path).read_text()

    def exists(self, path):
        return os.path.exists(path)

    def is_readable_dir(self, path):
        return os.path.isdir(path) and os.access(path, os.R_OK | os.X_OK)

    def run(self, argv, timeout=120):
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, check=False
            )
            return result.returncode, result.stdout, result.stderr
        except (OSError, subprocess.SubprocessError) as error:
            return 127, "", str(error)

    def which(self, name):
        return shutil.which(name)

    def env(self, name, default=None):
        return os.environ.get(name, default)

    def make_probe(self, workspace, name):
        """Create and remove exactly one owned probe directory (explicit modes)."""
        path = Path(workspace) / name
        write_ok = False
        try:
            path.mkdir(parents=False, exist_ok=False)
            (path / "owned-probe").write_text("photogram-dev uid probe\n")
            write_ok = (path / "owned-probe").read_text() == "photogram-dev uid probe\n"
        except OSError:
            write_ok = False
        finally:
            shutil.rmtree(path, ignore_errors=True)
        return {"path": str(path), "write_ok": write_ok, "cleaned": not path.exists()}


def load_manifest(path=MANIFEST_PATH):
    return json.loads(Path(path).read_text())


def _check(name, ok, detail=""):
    return {"name": name, "ok": bool(ok), "detail": detail}


def _closure_check(inspector, name, binary):
    code, stdout, stderr = inspector.run(["ldd", binary])
    text = stdout + stderr
    if code != 0:
        return _check(f"closure.{name}", False, f"ldd exit {code}: {stderr.strip()}")
    if "not found" in text:
        missing = sorted({line.split()[0] for line in text.splitlines() if "not found" in line})
        return _check(f"closure.{name}", False, f"unresolved: {missing}")
    offenders = sorted(
        {
            token
            for line in text.splitlines()
            for token in [line.split("=>")[-1].strip().split(" ")[0]]
            if token.startswith("/") and any(m in token for m in PROHIBITED_CLOSURE_MARKERS)
        }
    )
    if offenders:
        return _check(f"closure.{name}", False, f"prohibited resolved path: {offenders}")
    return _check(f"closure.{name}", True, "recursive loader closure resolved")


def build_doctor_report(manifest, inspector, workspace_env=None, manifest_path=None):
    """Pure report builder: no side effects beyond read-only inspection."""
    checks = []
    try:
        VALIDATOR.validate_manifest(manifest)
        checks.append(_check("manifest_self_consistent", True, VALIDATOR.evidence_identity(manifest)))
    except VALIDATOR.ContractError as error:
        checks.append(_check("manifest_self_consistent", False, str(error)))

    for name, control in manifest["controls"].items():
        path = control["path"]
        if not inspector.exists(path):
            checks.append(_check(f"control_identity.{name}", False, f"missing {path}"))
            continue
        actual = inspector.sha256(path)
        checks.append(
            _check(
                f"control_identity.{name}",
                actual == control["sha256"],
                f"{path} sha256={actual}",
            )
        )
        code, stdout, stderr = inspector.run([path, "-h"])
        if code != 0 or not stdout.strip():
            checks.append(_check(f"control_help.{name}", False, f"exit {code}"))
        else:
            help_sha = VALIDATOR.sha256_hex(stdout)
            checks.append(
                _check(
                    f"control_help.{name}",
                    help_sha == control["help_sha256"],
                    f"help sha256={help_sha}",
                )
            )
        checks.append(_closure_check(inspector, name, path))

    workspace = (workspace_env or inspector.env("PHOTOGRAM_WORKSPACE") or DEFAULT_WORKSPACE)
    workspace_readable = inspector.is_readable_dir(workspace)
    # Report-only: never create or write here from `doctor`.
    checks.append(
        _check("workspace_readable", workspace_readable, f"workspace={workspace}")
    )

    cpu_checks = [c for c in checks if c["name"] != "workspace_readable"]
    cpu_ready = all(c["ok"] for c in cpu_checks)
    host_prerequisites = {"workspace_readable": workspace_readable, "ok": workspace_readable}
    report = {
        "schema_version": VALIDATOR.SCHEMA_VERSION,
        "validator_version": VALIDATOR.VALIDATOR_VERSION,
        "command": "doctor",
        "cpu_ready": cpu_ready,
        "gpu_status": "not_checked",
        "ready": False,
        "host_prerequisites": host_prerequisites,
        "checks": checks,
        "evidence_identity": VALIDATOR.evidence_identity(manifest),
        "manifest_identity": {
            "base_image": manifest["identity"]["base_image"],
            "source_commit": manifest["identity"]["source_commit"],
            "source_tree": manifest["identity"]["source_tree"],
        },
        "controls": {
            name: {"path": control["path"], "sha256": control["sha256"]}
            for name, control in manifest["controls"].items()
        },
        "readiness_command": manifest["readiness"]["command"],
    }
    report["ready"] = (
        report["cpu_ready"]
        and report["gpu_status"] == "passed"
        and host_prerequisites["ok"]
    )
    VALIDATOR.validate_doctor_report(report)
    return report


def build_prepare_report(manifest, inspector, workspace_env=None, probe_name=".photogram-dev-probe"):
    """Explicit workspace validation: the ONLY mode that probes write access.

    Creates and removes exactly one owned probe directory; never touches other
    files and never fixes permissions with a DAC bypass.
    """
    workspace = (workspace_env or inspector.env("PHOTOGRAM_WORKSPACE") or DEFAULT_WORKSPACE)
    report = build_doctor_report(manifest, inspector, workspace_env=workspace)
    probe = inspector.make_probe(workspace, probe_name)
    write_ok = probe["write_ok"]
    report["command"] = "prepare"
    report["checks"].append(
        _check("workspace_uid_write", write_ok, f"probe={probe['path']} cleaned={probe['cleaned']}")
    )
    report["host_prerequisites"] = {
        "workspace_readable": report["host_prerequisites"]["workspace_readable"],
        "workspace_uid_writable": write_ok,
        "ok": report["host_prerequisites"]["workspace_readable"] and write_ok,
    }
    report["ready"] = report["cpu_ready"] and report["gpu_status"] == "passed" and report["host_prerequisites"]["ok"]
    return report


def build_gpu_smoke_report(manifest, probe):
    """Assemble the explicit GPU-smoke report from observed probe results."""
    checks = [_check(name, ok, detail) for name, ok, detail in probe["checks"]]
    gpu_ok = bool(probe["gpu_ok"]) and all(c["ok"] for c in checks)
    host_ok = bool(probe.get("host_ok", gpu_ok))
    report = {
        "schema_version": VALIDATOR.SCHEMA_VERSION,
        "validator_version": VALIDATOR.VALIDATOR_VERSION,
        "command": "gpu-smoke",
        "cpu_ready": bool(probe.get("cpu_ready", True)),
        "gpu_status": "passed" if gpu_ok else "failed",
        "ready": False,
        "host_prerequisites": {
            "nvidia_smi": bool(probe.get("nvidia_smi", False)),
            "nvidia_device_node": bool(probe.get("nvidia_device_node", False)),
            "ok": host_ok,
        },
        "checks": checks,
        "evidence_identity": VALIDATOR.evidence_identity(manifest),
        "gpu": {
            "driver": probe.get("driver"),
            "uuid": probe.get("uuid"),
            "compute_cap": probe.get("compute_cap"),
            "libcuda_realpath": probe.get("libcuda_realpath"),
            "cuinit_rc": probe.get("cuinit_rc"),
            "kernel_values": probe.get("kernel_values"),
        },
        "readiness_command": manifest["readiness"]["command"],
    }
    report["ready"] = (
        report["cpu_ready"] and gpu_ok and report["host_prerequisites"]["ok"]
    )
    VALIDATOR.validate_doctor_report(report)
    return report


def run_gpu_smoke(manifest, inspector, probe_dir):
    """Perform the real probe (compiles the shipped helpers). Explicit mode only."""
    probe_dir = Path(probe_dir)
    probe_dir.mkdir(parents=True, exist_ok=True)
    checks = []
    probe = {"cpu_ready": True, "checks": checks}
    expected_driver = manifest["gpu"]["policy_min_driver"]
    expected_cc = "8.6"
    probe["nvidia_device_node"] = inspector.exists("/dev/nvidia0") or inspector.exists("/dev/nvidiactl")
    nvidia_smi = inspector.which("nvidia-smi")
    probe["nvidia_smi"] = bool(nvidia_smi)
    if nvidia_smi:
        code, out, err = inspector.run(
            ["nvidia-smi", "--query-gpu=uuid,name,driver_version,compute_cap", "--format=csv,noheader"]
        )
        values = [v.strip() for v in out.strip().split(",")] if code == 0 and out.strip() else []
        driver = values[2] if len(values) > 2 else None
        cc = values[3] if len(values) > 3 else None
        probe["uuid"], probe["driver"], probe["compute_cap"] = (values[0] if values else None, driver, cc)
        checks.append(_check("nvidia_smi_identity", code == 0 and driver == expected_driver and cc == expected_cc,
                             f"driver={driver} cc={cc} expected={expected_driver}/{expected_cc}"))
    else:
        checks.append(_check("nvidia_smi_identity", False, "nvidia-smi absent"))

    build = probe_dir / "driver-resolve"
    code, out, err = inspector.run(
        ["nvcc", "-arch=sm_86", "-o", str(build), "/opt/photogram-dev/gpu-probe/driver-resolve.c", "-ldl"]
    )
    resolve_ok = code == 0
    realpath = None
    cuinit_rc = None
    if resolve_ok:
        code, out, err = inspector.run([str(build)])
        resolve_ok = code == 0
        for line in out.splitlines():
            if line.startswith("LIBCUDA_RESOLVED="):
                realpath = line.split("=", 1)[1]
            if line.startswith("cuInit rc="):
                cuinit_rc = int(line.split("=", 1)[1])
    probe["libcuda_realpath"] = realpath
    probe["cuinit_rc"] = cuinit_rc
    stub = bool(realpath) and any(m in realpath for m in PROHIBITED_CLOSURE_MARKERS)
    checks.append(_check("libcuda_dlopen", resolve_ok and cuinit_rc == 0 and not stub,
                         f"realpath={realpath} cuInit={cuinit_rc} stub={stub}"))

    launch = probe_dir / "cuda-launch"
    code, out, err = inspector.run(
        ["nvcc", "-arch=sm_86", "-o", str(launch), "/opt/photogram-dev/gpu-probe/cuda-launch.cu", "-ldl"]
    )
    kernel_ok = code == 0 and "RESULT: 1024 unique values exactly 2*i+1" in out
    probe["kernel_values"] = 1024 if kernel_ok else 0
    checks.append(_check("sm86_kernel_1024", kernel_ok, "1024-value sm_86 kernel result check"))

    probe["gpu_ok"] = all(c["ok"] for c in checks)
    probe["host_ok"] = probe["nvidia_device_node"] and probe["gpu_ok"]
    return probe


def _print(report, as_json):
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{report['command']}: cpu_ready={report['cpu_ready']} "
              f"gpu_status={report['gpu_status']} ready={report['ready']}")
        for check in report["checks"]:
            print(f"  [{'ok' if check['ok'] else 'FAIL'}] {check['name']}: {check['detail']}")
    return 0 if report["cpu_ready"] and report["gpu_status"] != "failed" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--workspace", default=None)
    sub = parser.add_subparsers(dest="command")
    for name in ("doctor", "prepare", "gpu-smoke"):
        command = sub.add_parser(name)
        command.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    command = args.command or "doctor"
    manifest = json.loads(Path(args.manifest).read_text())

    if command == "gpu-smoke":
        inspector = Inspector()
        probe_dir = Path(os.environ.get("PHOTOGRAM_PROBE_DIR", "/tmp/photogram-dev-probe"))
        try:
            probe = run_gpu_smoke(manifest, inspector, probe_dir)
        finally:
            shutil.rmtree(probe_dir, ignore_errors=True)
        report = build_gpu_smoke_report(manifest, probe)
    elif command == "prepare":
        report = build_prepare_report(manifest, Inspector(), workspace_env=args.workspace)
    else:
        report = build_doctor_report(manifest, Inspector(), workspace_env=args.workspace)
    return _print(report, args.json)


if __name__ == "__main__":
    sys.exit(main())
