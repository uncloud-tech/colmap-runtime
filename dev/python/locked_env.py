"""Exact public historical environment; validation never installs or downloads."""

from email.parser import BytesParser
import hashlib
import itertools
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import tarfile
from urllib.parse import urlsplit
import zipfile

PARENT_DIGEST = (
    "sha256:8993096b761a11d210afc5c49cbc8b8622d0b96d36fb539b348089c18d97ac0b"
)
PARENT = "ghcr.io/uncloud-tech/colmap-runtime-dev@" + PARENT_DIGEST
LOCK_SHA = "a22ac04ee8febc9f46f281d7b01d200e73e75f2d380bbc02b0bffc4992ee45cd"
ARCHIVE_SHA = "bd0d0568ccded07bbf1c87727230dc5dd0187e706a87da23c4de78388a229b78"
PYTHON_SHA = "5a91882290532b2719eaca77c0f3a7448bd73b9214e56df57bc59004560a80c6"
COLMAP_SHA = "fc896cb9b6a5883285673a6cd1c21d768c5a2d554d7c52748a6ae63aeb59e34c"
PREFIX = Path("/opt/colmap-python")
PUBLIC_HOSTS = {
    "github.com",
    "files.pythonhosted.org",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def public_url(uri):
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in PUBLIC_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("not an official public HTTPS artifact URL")
    return uri


def safe_relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in name:
        raise ValueError("unsafe artifact path")
    return path


def load_lock(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != LOCK_SHA:
        raise ValueError("environment lock hash mismatch")
    lock = json.loads(raw)
    rows = lock["artifacts"] + lock["dependency_artifacts"]
    if (
        type(lock["schema_version"]) is not int
        or lock["schema_version"] != 1
        or lock["image_digest"] != PARENT_DIGEST
        or len(rows) != 17
        or sum(r["size_bytes"] for r in rows) != 258592337
    ):
        raise ValueError("environment lock identity mismatch")
    for row in rows:
        public_url(row["uri"])
        safe_relative(
            row.get("destination", urlsplit(row["uri"]).path.rsplit("/", 1)[-1])
        )
    return lock


def verify_file(path, artifact):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("artifact is not a regular non-symlink file")
    before = path.stat()
    if before.st_size != artifact["size_bytes"] or sha256(path) != artifact["sha256"]:
        raise ValueError("artifact size/hash mismatch: " + path.name)
    after = path.stat()
    if (before.st_ino, before.st_mtime_ns, before.st_size) != (
        after.st_ino,
        after.st_mtime_ns,
        after.st_size,
    ):
        raise ValueError("artifact changed during verification")


def validate_tar_members(members):
    total = 0
    names = set()
    for member in members:
        path = safe_relative(member.name)
        if path.parts[0] != "python" or member.name in names:
            raise ValueError("unexpected/duplicate runtime archive member")
        names.add(member.name)
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ValueError("special runtime archive member")
        if member.issym() or member.islnk():
            target = (
                member.linkname
                if member.islnk()
                else posixpath.join(str(path.parent), member.linkname)
            )
            normalized = safe_relative(posixpath.normpath(target))
            if normalized.parts[0] != "python":
                raise ValueError("escaping archive link")
        total += member.size
        if total > 150000000:
            raise ValueError("runtime archive exceeds extraction limit")


def validate_archive(path):
    if sha256(path) != ARCHIVE_SHA:
        raise ValueError("runtime archive hash mismatch")
    with tarfile.open(path, "r:gz") as archive:
        validate_tar_members(archive.getmembers())
        stream = archive.extractfile("python/bin/python3.14")
        if (
            stream is None
            or hashlib.file_digest(stream, "sha256").hexdigest() != PYTHON_SHA
        ):
            raise ValueError("runtime interpreter hash mismatch")


def validate_wheel(path, artifact):
    path = Path(path)
    verify_file(path, artifact)
    tags = path.stem.rsplit("-", 3)[-3:]
    if len(tags) != 3:
        raise ValueError("invalid wheel filename")
    filename_tags = {
        "-".join(parts)
        for parts in itertools.product(*(tag.split(".") for tag in tags))
    }
    compatible = any(
        interpreter in ("cp314", "py3")
        and abi in ("cp314", "abi3", "none")
        and (
            platform == "any"
            or (platform.startswith("manylinux") and platform.endswith("_x86_64"))
        )
        for interpreter, abi, platform in (tag.split("-") for tag in filename_tags)
    )
    if not compatible:
        raise ValueError("incompatible locked wheel tag")
    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            safe_relative(member)
        metadata_names = [
            n for n in archive.namelist() if n.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError("wheel metadata is not unique")
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
        wheel = BytesParser().parsebytes(
            archive.read(metadata_names[0].rsplit("/", 1)[0] + "/WHEEL")
        )
        if (
            canonical(metadata["Name"]) != canonical(artifact["name"])
            or metadata["Version"] != artifact["version"]
            or set(wheel.get_all("Tag", [])) != filename_tags
        ):
            raise ValueError("wheel metadata/tag identity mismatch")
        return {
            "name": canonical(metadata["Name"]),
            "version": metadata["Version"],
            "tags": sorted(filename_tags),
            "license": str(
                metadata.get("License-Expression", metadata.get("License", ""))
            ),
            "notices": [
                n
                for n in archive.namelist()
                if any(k in n.lower() for k in ("license", "copying", "notice"))
            ],
        }


def requirements_text(lock):
    return "".join(
        f"{r['name']}=={r['version']} --hash=sha256:{r['sha256']}\n"
        for r in lock["dependency_artifacts"]
    )
