"""Fixed Python-only build/context/config gates; no publication or registry cache API."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

from dev.layer_binding import parse_reference, resolve_parent_reference
from dev.python.locked_env import PARENT, load_lock

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "dev/python"
CODE_FILES = {
    Path(name)
    for name in (
        "Dockerfile",
        "Dockerfile.layer",
        ".dockerignore",
        "environment-lock.json",
        "locked_env.py",
        "acquire.py",
        "install.py",
        "verify_runtime.py",
        "new_lineage.py",
        "bundle_python_native_libs.py",
    )
}
HELPERS = (
    "scripts/check_dev_contract.py",
    "scripts/check_dev_python_contract.py",
    "scripts/check_layer_image_contract.py",
    "scripts/collect_dev_python_native.sh",
    "scripts/collect_dev_python_native_runtime.sh",
    "dev/layer_binding.py",
    "dev/layer_identity.py",
)


PYLIBS = Path(".staged/pylibs")


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
    allowed = set(CODE_FILES | artifacts | helpers)
    pylibs = CONTEXT / PYLIBS
    if pylibs.is_dir():
        allowed |= {PYLIBS / path.name for path in pylibs.iterdir()}
    return frozenset(allowed)


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


def derived_validation_commands(
    context, image_tag, parent_reference, native_parent_record_json, layer_lock_json
):
    """Build the shared Python layer on the DIGEST-resolved native parent.

    ``parent_reference`` is the FULL published reference (``name@sha256:…``)
    resolved from the hash-bound record; the exact repository name is preserved
    verbatim (an authorised ephemeral registry such as ``127.0.0.1:5000/…`` is
    never redirected to a hardcoded registry). The embedded lock MUST bind the
    same parent digest the image is actually built on, so a typed reference
    cannot diverge from the lock.
    """
    if context.resolve() != CONTEXT:
        raise ValueError("only the Python layer context is allowed")
    digest = parse_reference(parent_reference)
    try:
        record = json.loads(native_parent_record_json)
    except json.JSONDecodeError as error:
        raise ValueError("native parent record is not valid JSON") from error
    if not isinstance(record, dict):
        raise ValueError("native parent record must be a JSON object")
    # The record must resolve to the SAME published reference the image is built
    # on; an unpublished/config-id/forged record is refused with a named reason.
    if resolve_parent_reference(record) != parent_reference:
        raise ValueError(
            "native parent record reference does not match the parent being built on"
        )
    try:
        lock = json.loads(layer_lock_json)
    except json.JSONDecodeError as error:
        raise ValueError("layer lock is not valid JSON") from error
    if not isinstance(lock, dict):
        raise ValueError("layer lock must be a JSON object")
    if lock.get("native_parent_digest") != digest:
        raise ValueError(
            "layer lock parent digest does not match the parent being built on"
        )
    if lock.get("content_identity") != "sha256:uncompressed-canonical-tar":
        raise ValueError("layer lock has the wrong content identity")
    parent = parent_reference
    return [
        ["docker", "pull", "--platform", "linux/amd64", parent],
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
            "--build-arg",
            f"PYTHON_PARENT={parent}",
            "--build-arg",
            f"LAYER_LOCK_JSON={layer_lock_json}",
            "--build-arg",
            f"NATIVE_PARENT_RECORD={native_parent_record_json}",
            "--file",
            str(context / "Dockerfile.layer"),
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
    parser.add_argument("mode", choices=("stage", "build", "config", "derived"))
    parser.add_argument("--parent-reference")
    parser.add_argument("--native-parent-record")
    parser.add_argument("--lock-file")
    parser.add_argument("--tag", default="colmap-dev:pr8-python-derived")
    args = parser.parse_args()
    if args.mode in ("stage", "build"):
        context = stage_context()
        if args.mode == "build":
            for command in validation_commands(context, "colmap-dev:pr8-python"):
                subprocess.run(command, check=True)
    elif args.mode == "derived":
        if (
            not args.parent_reference
            or not args.native_parent_record
            or not args.lock_file
        ):
            raise SystemExit(
                "derived mode requires --parent-reference, --native-parent-record "
                "and --lock-file"
            )
        context = stage_context()
        try:
            record_json = Path(args.native_parent_record).read_text()
            lock_json = Path(args.lock_file).read_text()
            commands = derived_validation_commands(
                context,
                args.tag,
                args.parent_reference,
                record_json,
                lock_json,
            )
        except (ValueError, OSError) as error:
            raise SystemExit(f"FAIL: {error}") from error
        for command in commands:
            subprocess.run(command, check=True)
    else:
        parent = json.loads(Path("reports/parent-config.json").read_text())[0]
        image = json.loads(Path("reports/image-config.json").read_text())[0]
        verify_configs(parent, image)
        print("PASS: unchanged native image configuration and parent layer prefix")


if __name__ == "__main__":
    main()
