"""Inspect every saved Docker layer, including files hidden by later layers.

A bounded credential-pattern/context-canary check, not a proof against all secrets.
The stronger boundary is an explicit context allowlist and no build credentials.
"""

import argparse
import hashlib
import json
from pathlib import PurePosixPath
import re
import tarfile

KEY_PATTERN = rb"-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]{64,}"
PATTERNS = [
    rb"BUILD_CONTEXT_EXCLUSION_CANARY",
    rb"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{40,}",
    rb"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{30,}",
]
# Exact public known-answer fixtures compiled into this Ubuntu library.
# Source: https://github.com/gnutls/gnutls/blob/3.8.3/lib/crypto-selftests-pk.c
# Hashes cover KEY_PATTERN matches, not arbitrary library content. No library-wide bypass.
PUBLIC_SELFTEST_HASHES = {
    "7f173f65ea04836d5d5fab00afa67897e71dbc01662db9bcbe807b8507b20487",
    "09cd48c2fbe44bf1e68565684f54c51299e75931ed42467cbc7be37c021e7ede",
    "a3d8965527fc3e07ed347c6d68cc95cc5511ae90a6ed7b9e9d443eceb2f5eaff",
    "d1dc75186fa035add68642556d4cdf68b2a1b74b4b60761b17f08fca7c79a606",
    "ac1e3b0c79d47689562ef8e864681b377afea59a786db073f647704adfcc82f4",
    "c41dc6cc1361b41b23dc261c959bed84bae2387ae3f196b1a60b0c61dd195d5b",
}


# SSH host keys are not credentials: they are world-readable the moment an
# instance serves SSH, and Vast's ssh launch mode requires a stock sshd setup
# (its startup starts sshd before any key-generation hook, and sshd exits when no
# host keys exist - incident 2026-09-28). Deliberately narrow: exact paths only,
# so this cannot be used to smuggle arbitrary key material.
SSH_HOST_KEY_PATHS = {
    "etc/ssh/ssh_host_rsa_key",
    "etc/ssh/ssh_host_ecdsa_key",
    "etc/ssh/ssh_host_ed25519_key",
    "etc/ssh/ssh_host_mldsa44_ed25519_key",
}


# SSH host keys are not credentials: they are world-readable as soon as an
# instance serves SSH, and the platform starts sshd from the image at container
# start (it does not generate keys at runtime), so a keyless image makes sshd
# exit with "no hostkeys available". Deliberately narrow: exact paths only, so
# this cannot be used to smuggle arbitrary key material.
SSH_HOST_KEY_PATHS = {
    "etc/ssh/ssh_host_rsa_key",
    "etc/ssh/ssh_host_ecdsa_key",
    "etc/ssh/ssh_host_ed25519_key",
    "etc/ssh/ssh_host_mldsa44_ed25519_key",
}


def check_member(name, data, final=True):
    path = PurePosixPath(name)
    if path.name.startswith(".env") or (
        ".ssh" in path.parts
        and path.name in {"authorized_keys", "id_rsa", "id_ed25519"}
    ):
        raise ValueError(f"Forbidden credential path in image: {name}")
    if any(re.search(pattern, data) for pattern in PATTERNS):
        # Never print the matching content.
        raise ValueError(f"Credential/canary pattern found in image member: {name}")
    for match in re.finditer(KEY_PATTERN, data):
        # Wait for the next block before classifying a key cut at a read boundary.
        if not final and match.end() == len(data):
            continue
        known = (
            str(path)
            in {
                "usr/lib/x86_64-linux-gnu/libgnutls.so.30.37.1",
                "lib/x86_64-linux-gnu/libgnutls.so.30.37.1",
            }
            and hashlib.sha256(match[0]).hexdigest() in PUBLIC_SELFTEST_HASHES
        ) or str(path) in SSH_HOST_KEY_PATHS
        if not known:
            raise ValueError(
                f"Unrecognized private-key material in image member: {name}"
            )


def audit(archive):
    files = 0
    with tarfile.open(archive, "r:*") as outer:
        manifests = json.load(outer.extractfile("manifest.json"))
        if len(manifests) != 1:
            raise ValueError("Exactly one candidate image required")
        for config in [manifests[0]["Config"]]:
            check_member(config, outer.extractfile(config).read())
        layers = manifests[0]["Layers"]
        if not isinstance(layers, list) or not layers:
            raise ValueError("Image must contain at least one layer")
        for layer in layers:
            with (
                outer.extractfile(layer) as stream,
                tarfile.open(fileobj=stream, mode="r|*") as contents,
            ):
                for member in contents:
                    check_member(member.name, b"")
                    if not member.isfile():
                        continue
                    files += 1
                    with contents.extractfile(member) as source:
                        carry = b""
                        while chunk := source.read(1024 * 1024):
                            check_member(member.name, carry + chunk, final=False)
                            carry = chunk[-16384:]
                        check_member(member.name, carry, final=True)
    return {
        "layers_scanned": len(layers),
        "files_scanned": files,
        "credential_patterns_found": 0,
        "scope": "context canary and listed credential patterns; not general vulnerability scanning",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    args = parser.parse_args()
    print(json.dumps(audit(args.archive)))
