import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MetadataTests(unittest.TestCase):
    def test_only_explicit_image_identity_fields_are_exported(self):
        path = ROOT / "scripts/public_metadata.py"
        self.assertTrue(path.exists(), "missing public metadata allowlist")
        spec = importlib.util.spec_from_file_location("public_metadata", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = {
            "Id": "sha256:example",
            "Architecture": "amd64",
            "Os": "linux",
            "Size": 123,
            "RepoDigests": [],
            "GraphDriver": {"Data": {"RootDir": "/host/private"}},
            "Config": {"Env": ["EXAMPLE_TOKEN=private"]},
            "UnknownFutureField": "private",
        }
        self.assertEqual(
            module.public_metadata([source]),
            {
                "Id": "sha256:example",
                "Architecture": "amd64",
                "Os": "linux",
                "Size": 123,
                "RepoDigests": [],
            },
        )
        with self.assertRaises(ValueError):
            module.public_metadata([])


if __name__ == "__main__":
    unittest.main()
