import hashlib
import importlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile


class LockedPythonTests(unittest.TestCase):
    def setUp(self):
        try:
            self.env = importlib.import_module("dev.python.locked_env")
        except ModuleNotFoundError:
            self.env = None
        self.assertIsNotNone(self.env, "locked shared Python validator is missing")

    def test_exact_lock_identity_and_totals(self):
        lock = self.env.load_lock(Path("dev/python/environment-lock.json"))
        rows = lock["artifacts"] + lock["dependency_artifacts"]
        self.assertEqual(len(rows), 17)
        self.assertEqual(sum(r["size_bytes"] for r in rows), 258592337)
        self.assertEqual(lock["interpreter"]["version"], "3.14.7")
        self.assertEqual(lock["image_digest"], self.env.PARENT_DIGEST)

    def test_altered_lock_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.json"
            path.write_bytes(
                Path("dev/python/environment-lock.json").read_bytes() + b" "
            )
            with self.assertRaisesRegex(ValueError, "lock hash"):
                self.env.load_lock(path)

    def test_file_sha_size_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file"
            path.write_bytes(b"abc")
            row = {"size_bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
            self.env.verify_file(path, row)
            path.write_bytes(b"abd")
            with self.assertRaises(ValueError):
                self.env.verify_file(path, row)
            alias = Path(directory) / "link"
            alias.symlink_to(path)
            with self.assertRaises(ValueError):
                self.env.verify_file(alias, row)

    def test_unsafe_destination_and_uri_rejected(self):
        for uri in (
            "http://github.com/a",
            "https://evil.test/a",
            "https://user:secret@github.com/a",
        ):
            with self.assertRaises(ValueError):
                self.env.public_url(uri)
        for name in ("../file", "/file", "wheelhouse/../../file"):
            with self.assertRaises(ValueError):
                self.env.safe_relative(name)

    def test_archive_escape_and_size_rejected(self):
        for name in ("/outside", "python/../../outside"):
            with self.assertRaises(ValueError):
                self.env.validate_tar_members([tarfile.TarInfo(name)])
        link = tarfile.TarInfo("python/bin/escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../outside"
        with self.assertRaises(ValueError):
            self.env.validate_tar_members([link])
        large = tarfile.TarInfo("python/large")
        large.size = 150000001
        with self.assertRaises(ValueError):
            self.env.validate_tar_members([large])

    def test_wheel_metadata_and_tag_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo-1.0-py3-none-any.whl"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "demo-1.0.dist-info/METADATA",
                    "Name: demo\nVersion: 1.0\nLicense: MIT — Unicode notice\n",
                )
                archive.writestr(
                    "demo-1.0.dist-info/WHEEL",
                    "Wheel-Version: 1.0\nTag: py3-none-any\n",
                )
            row = {
                "name": "demo",
                "version": "1.0",
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            self.assertEqual(self.env.validate_wheel(path, row)["name"], "demo")
            json.dumps(self.env.validate_wheel(path, row))
            row["version"] = "2.0"
            with self.assertRaises(ValueError):
                self.env.validate_wheel(path, row)

    def test_requirements_are_exact_hashed_wheels(self):
        lock = self.env.load_lock(Path("dev/python/environment-lock.json"))
        text = self.env.requirements_text(lock)
        self.assertEqual(len(text.splitlines()), 16)
        self.assertIn("pycolmap-cuda12==4.2.0 --hash=sha256:ebf769f7", text)
        self.assertNotIn("[all]", text)
        self.assertNotIn("https:", text)

    def test_archive_interpreter_hash_verified_without_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                entry = tarfile.TarInfo("python/bin/python3.14")
                entry.size = 3
                archive.addfile(entry, io.BytesIO(b"abc"))
            with self.assertRaisesRegex(ValueError, "archive hash"):
                self.env.validate_archive(path)
