"""Fail loudly on runtime incompatibility; CPU validation is not GPU acceptance."""

import argparse
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys


def cuda_providers(maps=None, nvidia_root=None):
    """Inspect libraries actually mapped in this process, not loader guesses."""
    root = Path(
        nvidia_root or Path(sys.prefix) / "lib/python3.14/site-packages/nvidia"
    ).resolve()
    text = Path("/proc/self/maps").read_text() if maps is None else maps
    result = {}
    for soname, directory in [
        ("libcudart.so.12", "cuda_runtime"),
        ("libcurand.so.10", "curand"),
    ]:
        paths = {
            Path(line.split()[-1]).resolve()
            for line in text.splitlines()
            if line.split() and soname in Path(line.split()[-1]).name
        }
        expected = root / directory / "lib"
        if len(paths) != 1 or not next(iter(paths)).is_relative_to(expected):
            raise RuntimeError(
                f"Unexpected CUDA provider for {soname}: {sorted(map(str, paths))}"
            )
        result[soname] = str(next(iter(paths)))
    return result


def assert_installer_free(root):
    root = Path(root)
    paths = [
        root / "lib/python3.14/ensurepip",
        root / "lib/python3.14/site-packages/pip",
    ]
    paths += list((root / "lib/python3.14/site-packages").glob("pip-*.dist-info"))
    paths += list((root / "bin").glob("pip*"))
    if any(path.exists() or path.is_symlink() for path in paths):
        raise RuntimeError("Build-only Python installer retained in final runtime")


def verify(mode, lock):
    if platform.python_version() != lock["python"]["version"]:
        raise RuntimeError("Python version differs from runtime lock")
    versions = {}
    for wheel in lock["wheels"]:
        version = importlib.metadata.version(wheel["name"])
        if version != wheel["version"]:
            raise RuntimeError(f"Version mismatch for {wheel['name']}")
        versions[wheel["name"]] = version
    # benchmark-v4 ships PyCOLMAP as a source build (patched MVS CUDA) rather
    # than a wheel; its name/version are still pinned and fail-closed.
    for build in lock.get("source_builds", []):
        version = importlib.metadata.version(build["name"])
        if version != build["version"]:
            raise RuntimeError(f"Version mismatch for {build['name']}")
        versions[build["name"]] = version
    # Do not truncate chained exceptions: pycolmap wraps the native loader error.
    for name in ("numpy", "scipy", "PIL.Image", "matplotlib", "pycolmap"):
        importlib.import_module(name)
    import pycolmap

    if not pycolmap.has_cuda:
        raise RuntimeError("PyCOLMAP was not built with CUDA support")
    result = {
        "mode": mode,
        "python": platform.python_version(),
        "packages": versions,
        "pycolmap_has_cuda": bool(pycolmap.has_cuda),
        "gpu_execution_validated": False,
        "cuda_providers": cuda_providers(),
    }
    if mode == "gpu":
        result["gpu_inventory"] = (
            subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,driver_version",
                    "--format=csv,noheader",
                ],
                text=True,
                timeout=30,
            )
            .strip()
            .splitlines()
        )
        if not result["gpu_inventory"]:
            raise RuntimeError("No GPU visible")
        # Inventory alone is not evidence of kernel execution; the canary is separate.
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["cpu", "gpu"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installer-free", action="store_true")
    args = parser.parse_args()
    if args.require_installer_free:
        assert_installer_free(sys.prefix)
    lock_path = Path(__file__).with_name("runtime-lock.json")
    result = verify(args.mode, json.loads(lock_path.read_text()))
    result["lock_sha256"] = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    result["installer_free_checked"] = args.require_installer_free
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
