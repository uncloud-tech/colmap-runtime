import importlib.util
import io
import json
import tarfile
import tempfile
import hashlib
from unittest.mock import patch
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LayerAuditTests(unittest.TestCase):
    def test_rejects_secret_files_and_content(self):
        path = ROOT / "scripts/audit_image.py"
        self.assertTrue(path.exists(), "missing all-layer audit")
        spec = importlib.util.spec_from_file_location("audit_image", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in [
            "root/.ssh/authorized_keys",
            "root/.ssh/id_ed25519",
            "opt/.env.canary",
        ]:
            with self.assertRaises(ValueError):
                module.check_member(name, b"innocent bytes")
        for data in [
            b"BUILD_CONTEXT_EXCLUSION_CANARY",
            b"-----BEGIN OPENSSH PRIVATE KEY-----\n" + b"A" * 80,
            b"github_pat_" + b"A" * 60,
        ]:
            with self.assertRaises(ValueError):
                module.check_member("opt/data", data)
        module.check_member("opt/runtime-lock.json", b'{"version":"1.0"}')
        # A parser's literal header string is not itself secret key material.
        module.check_member("lib/libcrypto.so", b"-----BEGIN PRIVATE KEY-----\0")
        # C++ Highs_ symbols contain the substring ghs_, not a GitHub token.
        module.check_member("lib/solver.so", b"Highs_" + b"SolverSymbol" * 5)
        with self.assertRaises(ValueError):
            module.check_member("opt/config", b'token="ghs_' + b"A" * 36 + b'"')

    def test_public_library_fixture_exception_is_exact_and_path_scoped(self):
        spec = importlib.util.spec_from_file_location(
            "audit_image", ROOT / "scripts/audit_image.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, "PUBLIC_SELFTEST_HASHES"))
        fixture = b"-----BEGIN RSA PRIVATE KEY-----\n" + b"A" * 80 + b"\n"
        digest = hashlib.sha256(fixture).hexdigest()
        path = "usr/lib/x86_64-linux-gnu/libgnutls.so.30.37.1"
        with patch.object(module, "PUBLIC_SELFTEST_HASHES", {digest}):
            module.check_member(path, fixture + b"-----END RSA PRIVATE KEY-----")
            with self.assertRaises(ValueError):
                module.check_member("opt/unrelated", fixture)
            with self.assertRaises(ValueError):
                module.check_member(path, fixture.replace(b"AAA", b"BBB"))
            module.check_member(path, fixture[:100], final=False)
            with self.assertRaises(ValueError):
                module.check_member(path, fixture[:100], final=True)

    def test_scans_lower_layers_config_and_chunk_boundaries(self):
        path = ROOT / "scripts/audit_image.py"
        spec = importlib.util.spec_from_file_location("audit_image", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def packed(members):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                for name, data in members.items():
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
            return stream.getvalue()

        def image(first, config=b"{}"):
            return packed(
                {
                    "manifest.json": json.dumps(
                        [{"Config": "config.json", "Layers": ["old.tar", "new.tar"]}]
                    ).encode(),
                    "config.json": config,
                    "old.tar": packed({"opt/file": first}),
                    "new.tar": packed({"opt/.wh.file": b""}),
                }
            )

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "image.tar"
            archive.write_bytes(image(b"safe"))
            self.assertEqual(module.audit(archive)["layers_scanned"], 2)
            # Deletion in a later layer cannot hide the original secret.
            secret = b"x" * (1024 * 1024 - 10) + b"BUILD_CONTEXT_EXCLUSION_CANARY"
            archive.write_bytes(image(secret))
            with self.assertRaises(ValueError):
                module.audit(archive)
            archive.write_bytes(image(b"safe", b"BUILD_CONTEXT_EXCLUSION_CANARY"))
            with self.assertRaises(ValueError):
                module.audit(archive)
            archive.write_bytes(
                packed(
                    {
                        "manifest.json": json.dumps(
                            [{"Config": "config.json", "Layers": []}]
                        ).encode(),
                        "config.json": b"{}",
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "layer"):
                module.audit(archive)


if __name__ == "__main__":
    unittest.main()
