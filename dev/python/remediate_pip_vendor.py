#!/usr/bin/env python3
"""R570-only pip vendor remediation; historical lock and scientific wheels unchanged.

Run in the network-enabled image stage after locked Python installation.
The obsolete pkg_resources backend is unsupported by pip on Python 3.14.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile

ARTIFACTS = {
    "urllib3": ("2.8.0", "https://files.pythonhosted.org/packages/92/9d/c4e665119135114480843e7ab388fa94d8480650450e6f8e26b70d323a4c/urllib3-2.8.0-py3-none-any.whl", "0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3"),
    "msgpack": ("1.2.3", "https://files.pythonhosted.org/packages/0a/e7/bb605a7bab2d8425a64b3fa762b39dc1bf1c7e3f11ba6fb5413d6db0ff8c/msgpack-1.2.3.tar.gz", "32edb81a2b5eb7cd7c9d941b2bfbbb082fd2cd09e0e725930316af6b708db186"),
}


def remediate(vendor, downloads):
    vendor = Path(vendor)
    for name, (version, url, digest) in ARTIFACTS.items():
        archive = downloads / url.rsplit("/", 1)[1]
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise ValueError(f"hash mismatch: {name}")
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            if name == "urllib3":
                with zipfile.ZipFile(archive) as stream:
                    stream.extractall(scratch)
                source = scratch / name
            else:
                with tarfile.open(archive) as stream:
                    stream.extractall(scratch, filter="data")
                source = scratch / f"{name}-{version}" / name
            assert (source / "__init__.py").is_file()
            shutil.rmtree(vendor / name)
            shutil.copytree(source, vendor / name)
    # Remove actual obsolete code, not just its scanner metadata.
    shutil.rmtree(vendor / "pkg_resources")
    versions = vendor / "vendor.txt"
    lines = []
    for line in versions.read_text().splitlines():
        if line.strip().startswith("setuptools=="):
            continue
        for name, (version, _, _) in ARTIFACTS.items():
            if line.strip().startswith(name + "=="):
                line = line[:len(line) - len(line.lstrip())] + name + "==" + version
        lines.append(line)
    versions.write_text("\n".join(lines) + "\n")
    bom_path = vendor / "bom.cdx.json"
    bom = json.loads(bom_path.read_text())
    bom["components"] = [c for c in bom["components"] if c.get("name") != "setuptools"]
    for c in bom["components"]:
        if c.get("name") in ARTIFACTS:
            name = c["name"]
            c["version"] = ARTIFACTS[name][0]
            c["purl"] = c["bom-ref"] = f"pkg:pypi/{name}@{c['version']}"
    bom_path.write_text(json.dumps(bom, indent=2) + "\n")


def main():
    import sys
    assert sys.version_info[:2] == (3, 14)
    vendor = Path(importlib.util.find_spec("pip").origin).parent / "_vendor"
    with tempfile.TemporaryDirectory() as scratch:
        downloads = Path(scratch)
        for _, url, _ in ARTIFACTS.values():
            with urllib.request.urlopen(url, timeout=60) as response:
                (downloads / url.rsplit("/", 1)[1]).write_bytes(response.read())
        remediate(vendor, downloads)
    print(json.dumps({"updates": ARTIFACTS, "removed": "pip._vendor.pkg_resources (unsupported on Python 3.14)"}))


if __name__ == "__main__":
    main()
