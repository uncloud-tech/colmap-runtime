"""Exact existing artifact identity and anonymous registry verification; never build."""

import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

IMAGE_ID = "sha256:37f08c781f6fa456c20fe5faaef9d733ef2b7523c8925e4d83c9d1fb342739e7"
ZIP_SIZE = 6751321833
ZIP_SHA = "024cc07f3318e9adc3508d4ed49c074c340b048c4c233f877f5be9de66942d9f"
REPOSITORY = "uncloud-tech/colmap-runtime-dev"


def verify_archive(path, size=ZIP_SIZE, digest=ZIP_SHA):
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if path.stat().st_size != size or actual != digest:
        raise ValueError("exact artifact ZIP size/digest mismatch")


def verify_registry_bytes(manifest, config, digest, image_id=IMAGE_ID):
    if (
        "sha256:" + hashlib.sha256(manifest).hexdigest() != digest
        or json.loads(manifest)["config"]["digest"] != image_id
        or "sha256:" + hashlib.sha256(config).hexdigest() != image_id
        or json.loads(config).get("architecture") != "amd64"
        or json.loads(config).get("os") != "linux"
    ):
        raise ValueError("published anonymous manifest/config identity mismatch")


def anonymous(reference):
    prefix = "ghcr.io/" + REPOSITORY + "@sha256:"
    if not reference.startswith(prefix) or len(reference.removeprefix(prefix)) != 64:
        raise ValueError("unexpected immutable repository reference")
    digest = reference.split("@", 1)[1]
    with urlopen(
        "https://ghcr.io/token?service=ghcr.io&scope=repository:"
        + REPOSITORY
        + ":pull",
        timeout=60,
    ) as response:
        token = json.load(response)["token"]
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json",
    }
    base = "https://ghcr.io/v2/" + REPOSITORY
    with urlopen(
        Request(base + "/manifests/" + digest, headers=headers), timeout=60
    ) as response:
        manifest = response.read()
    with urlopen(
        Request(base + "/blobs/" + IMAGE_ID, headers=headers), timeout=60
    ) as response:
        config = response.read()
    verify_registry_bytes(manifest, config, digest)
    print(
        "PASS: anonymous manifest/config identity " + reference + " config=" + IMAGE_ID
    )


if __name__ == "__main__":
    if sys.argv[1] == "archive":
        verify_archive(Path(sys.argv[2]))
        print("PASS: exact ZIP size/SHA256")
    elif sys.argv[1] == "anonymous":
        anonymous(sys.argv[2])
    else:
        sys.exit("Refused unknown restore verification operation")
