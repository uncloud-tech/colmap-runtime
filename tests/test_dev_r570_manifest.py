import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load("check_dev_r570_manifest", ROOT / "scripts/check_dev_r570_manifest.py")
GENERATOR = _load("generate_manifest", ROOT / "dev/generate_manifest.py")

HELP_TEXT = "COLMAP 3.12\n  --PatchMatchStereo.sweep_tile arg (=32)\n"

FACTS = {
    "source_archive_sha256": "a" * 64,
    "controls": {
        "stock": {"sha256": "b" * 64, "help_sha256": VALIDATOR.sha256_hex(HELP_TEXT), "version_cc_sha256": "c" * 64},
        "seed": {"sha256": "d" * 64, "help_sha256": VALIDATOR.sha256_hex(HELP_TEXT), "version_cc_sha256": "e" * 64},
    },
    "mvs": {
        "stock": {"observed_elf": ["sm_86", "sm_89"], "observed_ptx": ["compute_70", "compute_90"], "native_sm120": False},
        "seed": {"observed_elf": ["sm_86", "sm_89"], "observed_ptx": ["compute_70", "compute_90"], "native_sm120": False},
    },
    "build": {"install_library_targets": ["colmap_util", "colmap_mvs"]},
    "toolchain": {
        "nvcc": "12.8",
        "cuda": "12.8",
        "gcc": "13.3.0",
        "cmake": "3.28.3",
        "ninja": "1.11.1",
        "python": "3.14.7",
    },
    "python_packages": [
        "contourpy==1.4.0", "cuda-toolkit==12.9.2.0", "cycler==0.12.1", "fonttools==4.65.0",
        "kiwisolver==1.5.1", "matplotlib==3.11.2", "numpy==2.5.3", "nvidia-cuda-runtime-cu12==12.9.79",
        "nvidia-curand-cu12==10.3.10.19", "packaging==26.3", "pillow==12.3.0",
        "pycolmap-cuda12==4.2.0", "pyparsing==3.3.2", "python-dateutil==2.9.0.post0",
        "scipy==1.18.1", "six==1.17.0",
    ],
    "apt_versions": {"jq": "1.7.1"},
}


def valid_manifest():
    return GENERATOR.build_manifest(json.loads(json.dumps(FACTS)))


class ManifestTests(unittest.TestCase):
    def test_valid_fixture_passes(self):
        manifest = valid_manifest()
        self.assertEqual(manifest["identity"]["source_commit"], VALIDATOR.SOURCE_COMMIT)

    def test_manifest_never_embeds_its_own_image_identity(self):
        manifest = valid_manifest()
        manifest["image_digest"] = "sha256:" + "f" * 64
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_manifest(manifest)

    def test_wrong_payload_identity_is_rejected(self):
        for mutate in (
            lambda m: m["identity"].__setitem__("source_commit", "0" * 40),
            lambda m: m["identity"].__setitem__("source_tree", "0" * 40),
            lambda m: m["identity"].__setitem__("base_image", "nvidia/cuda:12.9.0-devel-ubuntu24.04@sha256:" + "0" * 64),
            lambda m: m["seed_overlay"].__setitem__("patch_sha256", "0" * 64),
            lambda m: m["python"].__setitem__("environment_lock_sha256", "0" * 64),
            lambda m: m["build"].__setitem__("cuda_architectures", "89-real;120-real"),
            lambda m: m["build"].__setitem__("mvs_test_targets", ["colmap_mvs_mat_test"]),
            lambda m: m["mvs_evidence"].__setitem__("sm120_source_toggle_patch", True),
            lambda m: m["mvs_evidence"]["per_control"]["stock"].__setitem__("native_sm120", True),
            lambda m: m["mvs_evidence"]["per_control"]["stock"].__setitem__("observed_elf", ["sm_86"]),
            lambda m: m["gpu"].__setitem__("gpu_execution_validated", True),
            lambda m: m["gpu"].__setitem__("documented_min_driver", "570.195.03"),
            lambda m: m["toolchain"].__setitem__("boost", "1.83.0"),
            lambda m: m["python"].__setitem__("native_loader_cuda129", True),
            lambda m: m["controls"]["stock"].__setitem__("path", "/opt/colmap-pr8/bin/colmap"),
            lambda m: m["readiness"].__setitem__("command", "colmap"),
        ):
            with self.subTest(mutate=mutate):
                manifest = valid_manifest()
                mutate(manifest)
                with self.assertRaises(VALIDATOR.ContractError):
                    VALIDATOR.validate_manifest(manifest)

    def test_evidence_identity_tracks_payload(self):
        first = VALIDATOR.evidence_identity(valid_manifest())
        changed = valid_manifest()
        changed["controls"]["seed"]["sha256"] = "1" * 64
        self.assertNotEqual(first, VALIDATOR.evidence_identity(changed))

    def test_parse_helpers(self):
        self.assertEqual(GENERATOR.parse_sha256_file("b" * 64 + "  /opt/x\n"), "b" * 64)
        self.assertEqual(
            GENERATOR.arches_from_listing("ELF file 1: x.sm_86.cubin\nELF file 2: y.sm_89.cubin", "elf"),
            ["sm_86", "sm_89"],
        )
        self.assertEqual(
            GENERATOR.arches_from_listing("PTX file 1: x.sm_70.ptx\nPTX file 2: y.sm_90.ptx", "ptx"),
            ["compute_70", "compute_90"],
        )
        self.assertEqual(
            GENERATOR.parse_requirements("numpy==2.5.3 --hash=sha256:ab\n# c\nsix==1.17.0 --hash=sha256:cd\n"),
            ["numpy==2.5.3", "six==1.17.0"],
        )

    def test_cli_accepts_manifest_and_rejects_tampering(self):
        manifest = valid_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(manifest))
            self.assertEqual(VALIDATOR.main(["check", str(path)]), 0)
            manifest["identity"]["source_commit"] = "0" * 40
            path.write_text(json.dumps(manifest))
            with self.assertRaises(VALIDATOR.ContractError):
                VALIDATOR.main(["check", str(path)])

    def test_build_manifest_compatibility_check(self):
        contract = _load("check_dev_contract", ROOT / "scripts/check_dev_contract.py")
        manifest = valid_manifest()
        controls = manifest["controls"]
        fields = {
            "source_commit": manifest["identity"]["source_commit"],
            "source_archive_sha256": manifest["identity"]["source_archive_sha256"],
            "seed_patch_sha256": manifest["seed_overlay"]["patch_sha256"],
            "binary_path": controls["stock"]["path"],
            "binary_sha256": controls["stock"]["sha256"],
            "seed_binary_path": controls["seed"]["path"],
            "seed_binary_sha256": controls["seed"]["sha256"],
            "cuda_architectures": manifest["build"]["cuda_architectures"],
            "mvs_codegen_policy": manifest["mvs_evidence"]["policy"],
            "gpu_execution_validated": "false",
            "required_gpu_validation": manifest["gpu"]["required_gpu_validation"],
            "environment_lock_sha256": manifest["python"]["environment_lock_sha256"],
            "validator_version": "1",
            "readiness_command": manifest["readiness"]["command"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "manifest.json").write_text(json.dumps(manifest))
            (directory / "BUILD-MANIFEST.txt").write_text(
                "".join(f"{k}={v}\n" for k, v in fields.items())
            )
            contract.verify_r570(directory)
            (directory / "BUILD-MANIFEST.txt").write_text(
                "".join(f"{k}={v}\n" for k, v in fields.items() if k != "seed_binary_sha256")
            )
            with self.assertRaises(ValueError):
                contract.verify_r570(directory)


if __name__ == "__main__":
    unittest.main()
