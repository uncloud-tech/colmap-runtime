import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("scripts.restore_dev_image")

    def test_archive_exact_bytes_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.zip"
            path.write_bytes(b"verified fixture")
            digest = hashlib.sha256(b"verified fixture").hexdigest()
            self.module.verify_archive(path, 16, digest)
            for size, sha in ((15, digest), (16, "a" * 64)):
                with self.assertRaises(ValueError):
                    self.module.verify_archive(path, size, sha)

    def test_anonymous_manifest_and_config_bind_same_image(self):
        config = b'{"architecture":"amd64","os":"linux"}'
        image = "sha256:" + hashlib.sha256(config).hexdigest()
        manifest = json.dumps({"config": {"digest": image}}).encode()
        digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
        self.module.verify_registry_bytes(manifest, config, digest, image)
        for m, c, d, i in (
            (manifest, config, "sha256:" + "a" * 64, image),
            (manifest, config + b" ", digest, image),
            (manifest, config, digest, "sha256:" + "b" * 64),
        ):
            with self.assertRaises(ValueError):
                self.module.verify_registry_bytes(m, c, d, i)


if __name__ == "__main__":
    unittest.main()
