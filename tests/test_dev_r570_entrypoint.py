import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load("check_dev_r570_manifest", ROOT / "scripts/check_dev_r570_manifest.py")
GENERATOR = _load("generate_manifest", ROOT / "dev/generate_manifest.py")
TOOL = _load("photogram_dev", ROOT / "dev/photogram_dev.py")

HELP_TEXT = "COLMAP 3.12\n  --PatchMatchStereo.sweep_tile arg (=32)\n"
STOCK = "/opt/colmap-stock/bin/colmap"
SEED = "/opt/colmap-seed/bin/colmap"
STOCK_SHA = "b" * 64
SEED_SHA = "d" * 64


def fixture_manifest():
    facts = {
        "source_archive_sha256": "a" * 64,
        "controls": {
            "stock": {"sha256": STOCK_SHA, "help_sha256": VALIDATOR.sha256_hex(HELP_TEXT), "version_cc_sha256": "c" * 64},
            "seed": {"sha256": SEED_SHA, "help_sha256": VALIDATOR.sha256_hex(HELP_TEXT), "version_cc_sha256": "e" * 64},
        },
        "mvs": {
            "stock": {"observed_elf": ["sm_86", "sm_89"], "observed_ptx": ["compute_70", "compute_90"], "native_sm120": False},
            "seed": {"observed_elf": ["sm_86", "sm_89"], "observed_ptx": ["compute_70", "compute_90"], "native_sm120": False},
        },
        "build": {"install_library_targets": ["colmap_util"]},
        "toolchain": {"nvcc": "12.8", "cuda": "12.8", "gcc": "13.3.0", "cmake": "3.28.3", "ninja": "1.11.1", "python": "3.14.7"},
        "python_packages": [f"pkg{i}==1.0" for i in range(16)],
        "apt_versions": {"jq": "1.7.1"},
    }
    return GENERATOR.build_manifest(facts)


class FakeInspector:
    def __init__(self, *, hashes=None, present=None, readable=None, ldd=None, env=None, probe_write=True):
        self.hashes = hashes if hashes is not None else {STOCK: STOCK_SHA, SEED: SEED_SHA}
        self.present = present if present is not None else {STOCK, SEED}
        self.readable = readable if readable is not None else {"/work"}
        self.ldd = ldd if ldd is not None else {}
        self.env_map = env if env is not None else {}
        self.probe_write = probe_write

    def sha256(self, path):
        if str(path) not in self.hashes:
            raise FileNotFoundError(path)
        return self.hashes[str(path)]

    def exists(self, path):
        return str(path) in self.present

    def is_readable_dir(self, path):
        return str(path) in self.readable

    def run(self, argv, timeout=120):
        if argv[0] == "ldd":
            return 0, self.ldd.get(argv[1], ""), ""
        if argv[1] == "-h":
            return 0, HELP_TEXT, ""
        return 127, "", "not found"

    def which(self, name):
        return self.env_map.get("which:" + name)

    def env(self, name, default=None):
        return self.env_map.get(name, default)

    def make_probe(self, workspace, name):
        return {"path": f"{workspace}/{name}", "write_ok": self.probe_write, "cleaned": True}


def healthy_ldd():
    return (
        f"\tlinux-vdso.so.1 (0x0000)\n\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x1)\n"
        f"\tlibstdc++.so.6 => /lib/x86_64-linux-gnu/libstdc++.so.6 (0x2)\n"
    )


class DoctorTests(unittest.TestCase):
    def test_doctor_reports_cpu_ready_but_never_gpu_ready(self):
        manifest = fixture_manifest()
        inspector = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()})
        report = TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")
        self.assertTrue(report["cpu_ready"])
        self.assertEqual(report["gpu_status"], "not_checked")
        self.assertFalse(report["ready"])
        VALIDATOR.validate_doctor_report(report)

    def test_changed_control_hash_is_not_cpu_ready(self):
        manifest = fixture_manifest()
        inspector = FakeInspector(
            hashes={STOCK: "0" * 64, SEED: SEED_SHA}, ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()}
        )
        report = TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")
        self.assertFalse(report["cpu_ready"])
        VALIDATOR.validate_doctor_report(report)

    def test_prohibited_old_prefix_breaks_closure(self):
        manifest = fixture_manifest()
        ldd = "\tlibcolmap.so => /opt/colmap-pr8/lib/libcolmap.so (0x1)\n"
        inspector = FakeInspector(ldd={STOCK: ldd, SEED: healthy_ldd()})
        self.assertFalse(TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")["cpu_ready"])

    def test_unresolved_library_breaks_closure(self):
        manifest = fixture_manifest()
        inspector = FakeInspector(ldd={STOCK: "\tlibfoo.so => not found\n", SEED: healthy_ldd()})
        self.assertFalse(TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")["cpu_ready"])

    def test_unreadable_workspace_does_not_fake_readiness(self):
        manifest = fixture_manifest()
        inspector = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()}, readable=set())
        report = TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")
        self.assertTrue(report["cpu_ready"])  # payload itself is complete
        self.assertFalse(report["host_prerequisites"]["ok"])
        self.assertFalse(report["ready"])

    def test_prepare_is_the_only_mode_that_probes_writes(self):
        manifest = fixture_manifest()
        inspector = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()})
        doctor = TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")
        self.assertNotIn("workspace_uid_write", [c["name"] for c in doctor["checks"]])
        prepare_ok = TOOL.build_prepare_report(manifest, inspector, workspace_env="/work")
        self.assertEqual(prepare_ok["command"], "prepare")
        self.assertTrue(prepare_ok["host_prerequisites"]["workspace_uid_writable"])
        self.assertFalse(prepare_ok["ready"])  # still no GPU smoke
        failing = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()}, probe_write=False)
        prepare_fail = TOOL.build_prepare_report(manifest, failing, workspace_env="/work")
        self.assertFalse(prepare_fail["host_prerequisites"]["ok"])

    def test_gpu_smoke_is_explicit_and_gates_readiness(self):
        manifest = fixture_manifest()
        passed = {
            "checks": [
                ("nvidia_smi_identity", True, "driver=570.195.03"),
                ("libcuda_dlopen", True, "realpath=/usr/lib/libcuda.so.1"),
                ("sm86_kernel_1024", True, "1024"),
            ],
            "gpu_ok": True, "host_ok": True, "nvidia_smi": True, "nvidia_device_node": True,
            "cpu_ready": True, "driver": "570.195.03", "uuid": "GPU-test", "compute_cap": "8.6",
            "libcuda_realpath": "/usr/lib/x86_64-linux-gnu/libcuda.so.1", "cuinit_rc": 0, "kernel_values": 1024,
        }
        report = TOOL.build_gpu_smoke_report(manifest, passed)
        self.assertEqual(report["gpu_status"], "passed")
        self.assertTrue(report["ready"])
        VALIDATOR.validate_doctor_report(report)

        failed = dict(passed)
        failed["gpu_ok"] = False
        failed["checks"] = passed["checks"][:1] + [("libcuda_dlopen", False, "cuInit!=0")]
        report = TOOL.build_gpu_smoke_report(manifest, failed)
        self.assertEqual(report["gpu_status"], "failed")
        self.assertFalse(report["ready"])

    def test_validator_rejects_cpu_only_ready_and_doctored_gpu(self):
        manifest = fixture_manifest()
        inspector = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()})
        report = TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")
        report["ready"] = True  # cpu alone must not imply ready
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_doctor_report(report)
        report = TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")
        report["gpu_status"] = "passed"  # default doctor must stay not_checked
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_doctor_report(report)

    def test_evidence_identity_present_and_stable(self):
        manifest = fixture_manifest()
        inspector = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()})
        report = TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")
        self.assertEqual(report["evidence_identity"], VALIDATOR.evidence_identity(manifest))


class EntrypointAndRecipeTests(unittest.TestCase):
    def test_entrypoint_checks_both_controls_and_never_selects_path(self):
        text = (ROOT / "dev/entrypoint.r570.sh").read_text()
        self.assertIn("sha256sum --status -c /opt/photogram-dev/controls/stock.sha256", text)
        self.assertIn("sha256sum --status -c /opt/photogram-dev/controls/seed.sha256", text)
        self.assertNotIn("export PATH", text)
        self.assertIn("a 'colmap' binary is on PATH", text)
        self.assertIn("doctor|prepare|gpu-smoke", text)

    def test_recipe_pins_and_controls(self):
        text = (ROOT / "dev/Dockerfile.r570").read_text()
        self.assertIn(VALIDATOR.BASE_IMAGE, text)
        self.assertIn("c6ab4f897c94f10b15bdecc442dcfce4688f1b76", text)
        self.assertIn("5488323854cd99a7d785ada78e4106cb44e3c518", text)
        self.assertIn(VALIDATOR.SEED_PATCH_SHA256, text)
        self.assertIn("86-real;89-real;120-real;70-virtual", text)
        self.assertIn("/opt/colmap-stock", text)
        self.assertIn("/opt/colmap-seed", text)
        self.assertIn("seed-minimal-d7ffb9c.patch", text)
        # Never place a single control prefix on the loader path.
        self.assertNotIn("ENV LD_LIBRARY_PATH=", text)
        # Base digest must be the 12.8.1 pin, never 12.9.
        self.assertIn("nvidia/cuda:12.8.1-devel-ubuntu24.04@sha256:", text)
        self.assertNotIn("nvidia/cuda:12.9", text)


if __name__ == "__main__":
    unittest.main()
