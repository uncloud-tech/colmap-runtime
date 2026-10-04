import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "dev_contract", ROOT / "scripts/check_dev_contract.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DevContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.contract = {
            "schema_version": 1,
            "source_repo": "https://github.com/uncloud-tech/colmap",
            "source_commit": "340f78310590cefda7cd3bb61ff0775ae5e2b59f",
            "source_tarball_sha256": "350f219ff4c07f68a9a834e0838d280d1a7f45884e0aa97182229401fe58695e",
            "binary_path": "/opt/colmap-pr8/bin/colmap",
            "binary_sha256": "a" * 64,
            "cuda_architectures": "89-real;120-real",
            "mvs_cuda_architectures": "89-real;90-virtual",
            "sweep_tile_option": "--PatchMatchStereo.sweep_tile",
            "sweep_tile_values": [0, 8, 16, 32],
            "compact_prng_default": "0",
        }
        self.write_contract()
        (self.directory / "BUILD-MANIFEST.txt").write_text(
            "source_commit=340f78310590cefda7cd3bb61ff0775ae5e2b59f\n"
            "binary_sha256=" + "a" * 64 + "\n"
            "cuda_architectures=89-real;120-real\n"
        )
        (self.directory / "binary-sha256.txt").write_text(
            "a" * 64 + "  /opt/colmap-pr8/bin/colmap\n"
        )
        (self.directory / "patch-match-help.txt").write_text(
            "  --PatchMatchStereo.sweep_tile arg (=32)\n"
        )
        (self.directory / "runtime-defaults.txt").write_text(
            "COLMAP_PATCH_MATCH_COMPACT_PRNG=0\ncolmap=/opt/colmap-pr8/bin/colmap\n"
        )

    def write_contract(self):
        (self.directory / "image-contract.json").write_text(json.dumps(self.contract))

    def test_baked_contract_matches_independent_evidence(self):
        module.verify(self.directory)

    def test_changed_binary_is_rejected(self):
        (self.directory / "binary-sha256.txt").write_text(
            "b" * 64 + "  /opt/colmap-pr8/bin/colmap\n"
        )
        with self.assertRaises(ValueError):
            module.verify(self.directory)

    def test_wrong_source_architecture_or_default_is_rejected(self):
        for key, value in (
            ("source_commit", "2a5c9c81b2e77f10aad25582679c8d344c3f6694"),
            ("cuda_architectures", "86-real;120-real"),
            ("compact_prng_default", "1"),
            ("binary_sha256", "not-a-hash"),
        ):
            with self.subTest(key=key):
                original = self.contract[key]
                self.contract[key] = value
                self.write_contract()
                with self.assertRaises(ValueError):
                    module.verify(self.directory)
                self.contract[key] = original

    def test_missing_runtime_option_is_rejected(self):
        (self.directory / "patch-match-help.txt").write_text("other options\n")
        with self.assertRaises(ValueError):
            module.verify(self.directory)

    def test_enabled_compact_prng_default_is_rejected(self):
        (self.directory / "runtime-defaults.txt").write_text(
            "COLMAP_PATCH_MATCH_COMPACT_PRNG=1\ncolmap=/opt/colmap-pr8/bin/colmap\n"
        )
        with self.assertRaises(ValueError):
            module.verify(self.directory)

    def test_stale_binary_on_path_is_rejected(self):
        (self.directory / "runtime-defaults.txt").write_text(
            "COLMAP_PATCH_MATCH_COMPACT_PRNG=0\ncolmap=/opt/colmap-pr3/bin/colmap\n"
        )
        with self.assertRaises(ValueError):
            module.verify(self.directory)

    def test_cli_missing_evidence_fails_closed(self):
        (self.directory / "image-contract.json").unlink()
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/check_dev_contract.py"),
                str(self.directory),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
