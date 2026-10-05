"""Collect/verify CPU-only shared runtime evidence; never changes the installation."""

import argparse
import importlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import sysconfig

from dev.python.install import alias_targets, distributions, validate_distributions
from dev.python.locked_env import COLMAP_SHA, PREFIX, PYTHON_SHA, load_lock, sha256

NATIVE_PATH = "/opt/colmap-pr8/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
NATIVE_ENV = f"PATH={NATIVE_PATH}\nLD_LIBRARY_PATH=/opt/deps/lib:/opt/colmap-pr8/lib\nCOLMAP_PATCH_MATCH_COMPACT_PRNG=0\n"
SNAPSHOT_FILES = (
    "binary-sha256.txt",
    "native-env.txt",
    "runtime-defaults.txt",
    "native-library-resolution.txt",
    "native-library-files.sha256",
    "native-tools.sha256",
    "native-source-identity.txt",
    "system-packages.txt",
)


def read_native_snapshot(directory):
    return {name: (directory / name).read_text() for name in SNAPSHOT_FILES}


def file_inventory(prefix):
    result = {}
    for path in sorted(prefix.rglob("*")):
        if path == prefix / "runtime-manifest.json":
            continue
        name = str(path.relative_to(prefix))
        if path.is_symlink():
            if not path.resolve().is_relative_to(prefix.resolve()):
                raise ValueError("escaping installed symlink")
            result[name] = {"link": str(path.readlink())}
        elif path.is_file():
            result[name] = {"sha256": sha256(path), "size_bytes": path.stat().st_size}
        elif not path.is_dir():
            raise ValueError("special installed file")
    return result


def verify_installed_files(prefix, expected):
    if file_inventory(prefix) != expected:
        raise ValueError("shared runtime file inventory changed")


def validate_runtime(evidence, lock):
    interpreter = evidence["interpreter"]
    if (
        type(evidence.get("schema_version")) is not int
        or evidence["schema_version"] != 1
        or interpreter["path"] != str(PREFIX / "bin/python3.14")
        or interpreter["prefix"] != str(PREFIX)
        or interpreter["base_prefix"] != str(PREFIX)
        or interpreter["version"] != "3.14.7"
        or interpreter["sha256"] != PYTHON_SHA
        or evidence["aliases"]
        != {str(k): str(v) for k, v in alias_targets(PREFIX).items()}
    ):
        raise ValueError("shared runtime/interpreter/alias identity differs")
    validate_distributions(evidence["distributions"], lock)
    before, after = evidence["native_before"], evidence["native_after"]
    if (
        before != after
        or before["native-env.txt"] != NATIVE_ENV
        or before["binary-sha256.txt"] != f"{COLMAP_SHA}  /opt/colmap-pr8/bin/colmap\n"
    ):
        raise ValueError("native binary/source/tool/library/environment changed")
    libraries = evidence["python_libraries"]
    if len(libraries) != 2:
        raise ValueError("expected exactly wheel cudart and curand mappings")
    for component, filename in (
        ("cuda_runtime", "libcudart.so.12"),
        ("curand", "libcurand.so.10"),
    ):
        expected = str(
            PREFIX
            / "lib/python3.14/site-packages/nvidia"
            / component
            / "lib"
            / filename
        )
        matches = [record for record in libraries if record["path"] == expected]
        if len(matches) != 1 or not re.fullmatch("[0-9a-f]{64}", matches[0]["sha256"]):
            raise ValueError("Python CUDA is not the locked wheel-local library")
    if not all(
        evidence["cpu_smoke"][name] is True
        for name in ("numeric", "rendering", "pycolmap")
    ):
        raise ValueError("CPU preparation smoke failed")
    if any(
        evidence["verification_scope"].get(name) is not False
        for name in ("gpu_validated", "mps_validated", "reference_map_gate_passed")
    ):
        raise ValueError("GPU correctness must remain pending")


def validate_native_child(resolution, environment, native):
    normalized = re.sub(r" \(0x[0-9a-f]+\)", "", resolution)
    if (
        normalized != native["native-library-resolution.txt"]
        or environment != NATIVE_ENV
    ):
        raise ValueError(
            "native child after Python imports changed libraries/environment"
        )


def cpu_smoke():
    import matplotlib
    import numpy as np
    from scipy.linalg import solve

    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from PIL import Image
    import pycolmap

    np.testing.assert_allclose(
        solve(np.array([[2.0, 0.0], [0.0, 4.0]]), np.array([4.0, 8.0])), [2.0, 2.0]
    )
    figure = Figure(figsize=(1, 1))
    figure.subplots().plot([0, 1], [0, 1])
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    buffer.seek(0)
    with Image.open(buffer) as image:
        image.load()
        if image.width <= 0:
            raise ValueError("synthetic rendering failed")
    reconstruction = pycolmap.Reconstruction()
    camera = pycolmap.Camera(
        model="PINHOLE",
        width=32,
        height=24,
        params=[20.0, 20.0, 16.0, 12.0],
        camera_id=1,
    )
    reconstruction.add_camera(camera)
    if reconstruction.num_cameras() != 1:
        raise ValueError("synthetic PyCOLMAP camera preparation failed")
    imports = {}
    for name in (
        "contourpy",
        "cycler",
        "fontTools",
        "kiwisolver",
        "matplotlib",
        "numpy",
        "packaging",
        "PIL",
        "pycolmap",
        "pyparsing",
        "dateutil",
        "scipy",
        "six",
        "nvidia.cuda_runtime",
        "nvidia.curand",
    ):
        module = importlib.import_module(name)
        imports[name] = getattr(module, "__version__", "namespace")
    return {"numeric": True, "rendering": True, "pycolmap": True, "imports": imports}


def collect_runtime(prefix, lock, scratch, native_before, native_after):
    smoke = cpu_smoke()
    child_resolution = subprocess.check_output(
        ["ldd", "/opt/colmap-pr8/bin/colmap"], text=True
    )
    child_environment = "".join(
        f"{key}={os.environ.get(key, '')}\n"
        for key in ("PATH", "LD_LIBRARY_PATH", "COLMAP_PATCH_MATCH_COMPACT_PRNG")
    )
    validate_native_child(child_resolution, child_environment, native_after)
    mapped = set()
    for line in Path("/proc/self/maps").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 6 and any(
            name in fields[-1] for name in ("libcudart.so", "libcurand.so")
        ):
            mapped.add(str(Path(fields[-1]).resolve()))
    evidence = {
        "schema_version": 1,
        "interpreter": {
            "path": str(Path(sys.executable).resolve()),
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
            "version": platform.python_version(),
            "release": "3.14.7+20260924",
            "sha256": sha256(sys.executable),
            "soabi": sysconfig.get_config_var("SOABI"),
        },
        "aliases": {
            str(alias): str(alias.resolve()) for alias in alias_targets(prefix)
        },
        "distributions": distributions(),
        "artifacts": lock["artifacts"] + lock["dependency_artifacts"],
        "bootstrap": {
            "pip": "26.2.1",
            "ensurepip_wheel_sha256": sha256(
                next((prefix / "lib/python3.14/ensurepip/_bundled").glob("pip-*.whl"))
            ),
        },
        "invocation": {
            "executable": sys.executable,
            "argv": sys.argv,
            "native_child_resolution": re.sub(
                r" \(0x[0-9a-f]+\)", "", child_resolution
            ),
            "environment": {
                k: os.environ.get(k, "")
                for k in ("PATH", "LD_LIBRARY_PATH", "COLMAP_PATCH_MATCH_COMPACT_PRNG")
            },
        },
        "native_before": native_before,
        "native_after": native_after,
        "python_libraries": [{"path": p, "sha256": sha256(p)} for p in sorted(mapped)],
        "cpu_smoke": smoke,
        "verification_scope": {
            "gpu_validated": False,
            "mps_validated": False,
            "reference_map_gate_passed": False,
            "root_read_only": os.statvfs("/").f_flag & os.ST_RDONLY != 0,
            "network_policy": "container/build network disabled by caller",
            "scratch": str(scratch),
        },
    }
    validate_runtime(evidence, lock)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bake", action="store_true")
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    lock = load_lock(PREFIX / "environment-lock.json")
    args.scratch.mkdir(parents=True, exist_ok=True)
    evidence = collect_runtime(
        PREFIX,
        lock,
        args.scratch,
        read_native_snapshot(PREFIX / "native-parent"),
        read_native_snapshot(args.after),
    )
    manifest = PREFIX / "runtime-manifest.json"
    if args.bake:
        from scripts.check_dev_contract import verify_native
        from scripts.check_dev_python_contract import make_contract

        native = json.loads((PREFIX / "native-parent/image-contract.json").read_text())
        verify_native(PREFIX / "native-parent", native)
        evidence["installed_files"] = file_inventory(PREFIX)
        manifest.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
        contract = make_contract(native, evidence, sha256(manifest))
        Path("/opt/colmap-dev/image-contract.json").write_text(
            json.dumps(contract, sort_keys=True, indent=2) + "\n"
        )
        with Path("/opt/colmap-dev/BUILD-MANIFEST.txt").open("a") as stream:
            stream.write(
                f"python_prefix={PREFIX}\npython_environment_lock_sha256={contract['environment_lock_sha256']}\npython_runtime_manifest_sha256={sha256(manifest)}\n"
            )
    else:
        baked = json.loads(manifest.read_text())
        validate_runtime(baked, lock)
        verify_installed_files(PREFIX, baked["installed_files"])
        for key in (
            "interpreter",
            "aliases",
            "distributions",
            "artifacts",
            "bootstrap",
            "native_before",
            "native_after",
            "python_libraries",
        ):
            if evidence[key] != baked[key]:
                raise ValueError("observed versus baked runtime differs: " + key)
        subprocess.run(
            [sys.executable, "-I", "-B", "-m", "pip", "--isolated", "check"],
            check=True,
            stdout=sys.stderr,
        )
        if args.output is None:
            raise ValueError("verification output required")
        args.output.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    print(
        "PASS: exact shared interpreter/17 distributions, CPU imports/preparation, native library/source preservation"
    )


if __name__ == "__main__":
    main()
