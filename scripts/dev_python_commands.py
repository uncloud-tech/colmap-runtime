"""Fixed Python-only build/context/config gates; no publication or registry cache API."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

from dev.python.locked_env import PARENT, load_lock

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "dev/python"
CODE_FILES = {
    Path(name)
    for name in (
        "Dockerfile",
        ".dockerignore",
        "environment-lock.json",
        "locked_env.py",
        "acquire.py",
        "install.py",
        "verify_runtime.py",
    )
}
HELPERS = (
    "scripts/check_dev_contract.py",
    "scripts/check_dev_python_contract.py",
    "scripts/collect_dev_python_native.sh",
)


def allowed_context_paths(lock):
    artifacts = {
        Path(".staged/artifacts") / urlsplit(row["uri"]).path.rsplit("/", 1)[-1]
        for row in lock["artifacts"] + lock["dependency_artifacts"]
    }
    artifacts |= {
        Path(".staged/artifacts/requirements.txt"),
        Path(".staged/artifacts/license-inventory.json"),
    }
    helpers = {
        Path(".staged/helpers") / source
        if source.startswith("scripts/check_")
        else Path(".staged/helpers") / Path(source).name
        for source in HELPERS
    }
    return frozenset(CODE_FILES | artifacts | helpers)


def validate_context_inventory(paths, allowed):
    if paths != allowed:
        raise ValueError(
            "unexpected/missing build context members: "
            + str(sorted(map(str, paths ^ allowed)))
        )


def stage_context():
    lock = load_lock(CONTEXT / "environment-lock.json")
    for source in HELPERS:
        relative = (
            Path(source) if source.startswith("scripts/check_") else Path(source).name
        )
        destination = CONTEXT / ".staged/helpers" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            raise ValueError("staged helper is a symlink")
        shutil.copyfile(ROOT / source, destination)
    paths = set()
    for path in CONTEXT.rglob("*"):
        relative = path.relative_to(CONTEXT)
        if path.is_symlink():
            raise ValueError("symlink in build context")
        if relative.parts[0] == "__pycache__":
            continue
        if path.is_file():
            paths.add(relative)
    validate_context_inventory(paths, allowed_context_paths(lock))
    return CONTEXT


def validation_commands(context, image_tag):
    if context.resolve() != CONTEXT:
        raise ValueError("only the Python layer context is allowed")
    return [
        ["docker", "pull", "--platform", "linux/amd64", PARENT],
        [
            "docker",
            "buildx",
            "build",
            "--load",
            "--pull",
            "--platform",
            "linux/amd64",
            "--network=none",
            "--provenance=false",
            "--sbom=false",
            "--progress=plain",
            "--tag",
            image_tag,
            "--file",
            str(context / "Dockerfile"),
            str(context),
        ],
    ]


def verify_configs(parent, image):
    if any(
        record.get("Architecture") != "amd64" or record.get("Os") != "linux"
        for record in (parent, image)
    ):
        raise ValueError("wrong image platform")
    for key in (
        "Env",
        "Entrypoint",
        "Cmd",
        "WorkingDir",
        "User",
        "Shell",
        "Labels",
        "Volumes",
        "Healthcheck",
        "StopSignal",
        "ExposedPorts",
        "OnBuild",
    ):
        if parent["Config"].get(key) != image["Config"].get(key):
            raise ValueError("native image configuration changed: " + key)
    parent_layers = parent.get("RootFS", {}).get("Layers", [])
    if (
        parent_layers
        and image["RootFS"]["Layers"][: len(parent_layers)] != parent_layers
    ):
        raise ValueError("native parent layers are not an unchanged prefix")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "build", "config"))
    args = parser.parse_args()
    if args.mode in ("stage", "build"):
        context = stage_context()
        if args.mode == "build":
            for command in validation_commands(context, "colmap-dev:pr8-python"):
                subprocess.run(command, check=True)
    else:
        parent = json.loads(Path("reports/parent-config.json").read_text())[0]
        image = json.loads(Path("reports/image-config.json").read_text())[0]
        verify_configs(parent, image)
        print("PASS: unchanged native image configuration and parent layer prefix")


if __name__ == "__main__":
    main()
