import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

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
            "stock": {"observed_elf": ["sm_86", "sm_89"], "observed_ptx": ["compute_70", "compute_90"], "native_sm120": False,
                      "objects": {stem: {"elf": ["sm_86", "sm_89"], "ptx": ["compute_70", "compute_90"]}
                                  for stem in ("patch_match_cuda", "gpu_mat_prng", "gpu_mat_ref_image")}},
            "seed": {"observed_elf": ["sm_86", "sm_89"], "observed_ptx": ["compute_70", "compute_90"], "native_sm120": False,
                     "objects": {stem: {"elf": ["sm_86", "sm_89"], "ptx": ["compute_70", "compute_90"]}
                                 for stem in ("patch_match_cuda", "gpu_mat_prng", "gpu_mat_ref_image")}},
        },
        "build": {"install_library_targets": ["colmap_util"]},
        "toolchain": {"nvcc": "12.8", "cuda": "12.8", "gcc": "13.3.0", "cmake": "3.28.3", "ninja": "1.11.1", "python": "3.14.7"},
        "python_packages": [f"pkg{i}==1.0" for i in range(16)],
        "apt_versions": {"jq": "1.7.1"},
        "harness_files": {name: "a" * 64 for name in VALIDATOR.HARNESS_FILES},
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


class RealProbeInspector(TOOL.Inspector):
    """Real filesystem probe on a temp workspace; scripted control/loader checks.

    It inherits the production ``make_probe`` (real mkdir/write/rmtree) and only
    substitutes the read-only control inspection so ``prepare`` can run against
    a temp directory without the baked image controls.
    """

    def __init__(self, workspace):
        self.workspace = str(workspace)

    def sha256(self, path):
        return {STOCK: STOCK_SHA, SEED: SEED_SHA}[str(path)]

    def exists(self, path):
        return str(path) in {STOCK, SEED}

    def is_readable_dir(self, path):
        return str(path) == self.workspace

    def run(self, argv, timeout=120):
        if argv[0] == "ldd":
            return 0, healthy_ldd(), ""
        if argv[1] == "-h":
            return 0, HELP_TEXT, ""
        return 127, "", "not found"

    def which(self, name):
        return None

    def env(self, name, default=None):
        return self.workspace if name == "PHOTOGRAM_WORKSPACE" else default


class DoctorTests(unittest.TestCase):
    def _exit(self, report):
        with contextlib.redirect_stdout(io.StringIO()):
            return TOOL._print(report, True)

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
        self.assertTrue(prepare_ok["prepare_ok"])  # CPU-only prepare success
        self.assertFalse(prepare_ok["ready"])  # still no GPU smoke
        failing = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()}, probe_write=False)
        prepare_fail = TOOL.build_prepare_report(manifest, failing, workspace_env="/work")
        self.assertFalse(prepare_fail["host_prerequisites"]["ok"])
        self.assertFalse(prepare_fail["prepare_ok"])

    def test_exit_semantics_prepare_success_and_documented_doctor(self):
        manifest = fixture_manifest()
        healthy = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()})
        # Documented: a cpu-ready doctor is informational and exits 0.
        doctor = TOOL.build_doctor_report(manifest, healthy, workspace_env="/work")
        self.assertTrue(doctor["cpu_ready"])
        self.assertEqual(self._exit(doctor), 0)
        # A healthy CPU-only prepare is a success (prepare_ok) and exits 0, but
        # the full `ready` receipt stays reserved for an explicit gpu-smoke.
        prepare_ok = TOOL.build_prepare_report(manifest, healthy, workspace_env="/work")
        self.assertTrue(prepare_ok["prepare_ok"])
        self.assertFalse(prepare_ok["ready"])
        self.assertEqual(self._exit(prepare_ok), 0)
        # The concrete defect: a failed write probe must not exit 0.
        failing = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()}, probe_write=False)
        prepare_fail = TOOL.build_prepare_report(manifest, failing, workspace_env="/work")
        self.assertFalse(prepare_fail["prepare_ok"])
        self.assertFalse(prepare_fail["host_prerequisites"]["ok"])
        self.assertEqual(self._exit(prepare_fail), 1)

    def test_validator_requires_consistent_boolean_prepare_ok(self):
        manifest = fixture_manifest()
        inspector = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()})
        report = TOOL.build_prepare_report(manifest, inspector, workspace_env="/work")
        VALIDATOR.validate_doctor_report(report)  # valid as built
        missing = dict(report)
        missing.pop("prepare_ok")
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_doctor_report(missing)
        wrong_type = dict(report)
        wrong_type["prepare_ok"] = 1
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_doctor_report(wrong_type)
        inconsistent = dict(report)
        inconsistent["prepare_ok"] = False
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_doctor_report(inconsistent)

    def test_prepare_report_is_validated_on_build(self):
        manifest = fixture_manifest()
        inspector = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()})
        calls = []
        original = TOOL.VALIDATOR.validate_doctor_report

        def spy(report):
            calls.append(report)
            return original(report)

        TOOL.VALIDATOR.validate_doctor_report = spy
        try:
            report = TOOL.build_prepare_report(manifest, inspector, workspace_env="/work")
        finally:
            TOOL.VALIDATOR.validate_doctor_report = original
        self.assertTrue(calls)
        # Any mutation after construction is still rejected independently.
        report["ready"] = True
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_doctor_report(report)

    def test_prohibited_markers_are_precise(self):
        self.assertNotIn("/nvidia/", TOOL.PROHIBITED_CLOSURE_MARKERS)
        self.assertIn("nvidia_cuda_runtime", TOOL.PROHIBITED_CLOSURE_MARKERS)
        self.assertIn("/dist-packages/", TOOL.PROHIBITED_CLOSURE_MARKERS)

    def test_host_injected_nvidia_driver_dir_is_not_prohibited(self):
        manifest = fixture_manifest()
        ldd = "\tlibcuda.so.1 => /usr/local/nvidia/lib64/libcuda.so.1 (0x1)\n"
        inspector = FakeInspector(ldd={STOCK: ldd, SEED: healthy_ldd()})
        report = TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")
        self.assertTrue(report["cpu_ready"])

    def test_wheel_local_cuda_stub_is_still_prohibited(self):
        manifest = fixture_manifest()
        ldd = (
            "\tlibcudart.so.12 => /opt/colmap-python/lib/python3.14/site-packages/"
            "nvidia/cuda_runtime/lib/libcudart.so.12 (0x1)\n"
        )
        inspector = FakeInspector(ldd={STOCK: ldd, SEED: healthy_ldd()})
        report = TOOL.build_doctor_report(manifest, inspector, workspace_env="/work")
        self.assertFalse(report["cpu_ready"])

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


class ProbeOwnershipIntegrationTests(unittest.TestCase):
    """Real filesystem tests for the owned probe directory (not the fake probe)."""

    def test_preexisting_probe_dir_survives_prepare_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            foreign = workspace / ".photogram-dev-probe"
            foreign.mkdir()
            sentinel = foreign / "sentinel.txt"
            sentinel.write_text("foreign content\n")

            inspector = RealProbeInspector(workspace)
            report = TOOL.build_prepare_report(
                fixture_manifest(), inspector, workspace_env=str(workspace)
            )

            # Prepare succeeded using a *different*, freshly created directory.
            self.assertTrue(report["prepare_ok"])
            # The pre-existing colliding directory and its sentinel are intact.
            self.assertTrue(sentinel.is_file())
            self.assertEqual(sentinel.read_text(), "foreign content\n")
            self.assertEqual(
                sorted(p.name for p in workspace.iterdir()),
                [".photogram-dev-probe"],
            )

    def test_probe_dir_is_created_and_fully_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            inspector = TOOL.Inspector()

            probe = inspector.make_probe(str(workspace), ".photogram-dev-probe")

            self.assertIsNotNone(probe["path"])
            self.assertTrue(probe["path"].startswith(str(workspace / ".photogram-dev-probe-")))
            self.assertTrue(probe["write_ok"])
            self.assertTrue(probe["cleaned"])
            self.assertFalse(Path(probe["path"]).exists())
            self.assertEqual(list(workspace.iterdir()), [])

    def test_cleanup_failure_marks_not_cleaned_and_prepare_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            inspector = RealProbeInspector(workspace)

            with mock.patch.object(
                TOOL.shutil, "rmtree", side_effect=OSError("forced cleanup failure")
            ):
                report = TOOL.build_prepare_report(
                    fixture_manifest(), inspector, workspace_env=str(workspace)
                )

            check = next(c for c in report["checks"] if c["name"] == "workspace_uid_write")
            self.assertFalse(check["ok"])
            self.assertIn("cleaned=False", check["detail"])
            self.assertFalse(report["prepare_ok"])
            self.assertFalse(report["host_prerequisites"]["ok"])
            self.assertFalse(report["host_prerequisites"]["workspace_probe_cleaned"])
            # The un-cleanable directory is exactly the one probe it owned.
            leftovers = [p.name for p in workspace.iterdir()]
            self.assertTrue(any(n.startswith(".photogram-dev-probe-") for n in leftovers))


class GpuIdentityPolicyTests(unittest.TestCase):
    def test_supported_arches_derived_from_manifest(self):
        manifest = fixture_manifest()
        self.assertEqual(TOOL.supported_compute_arches(manifest), (86, 89, 120))
        policy = TOOL.gpu_identity_policy(manifest)
        self.assertEqual(policy["supported_arches"], ["8.6", "8.9", "12.0"])
        self.assertEqual(policy["min_supported_arch"], "8.6")
        self.assertEqual(policy["kernel_probe_arch"], "sm_86")
        self.assertEqual(policy["min_driver"], "570.195.03")

    def test_sm89_host_with_newer_driver_passes_identity(self):
        manifest = fixture_manifest()
        result = TOOL.evaluate_gpu_identity(manifest, "571.10", "8.9")
        self.assertTrue(result["ok"])
        self.assertTrue(result["driver_ok"])
        self.assertTrue(result["arch_ok"])

    def test_sm120_host_passes_identity_and_is_noted(self):
        manifest = fixture_manifest()
        result = TOOL.evaluate_gpu_identity(manifest, "580.0", "12.0")
        self.assertTrue(result["ok"])
        self.assertTrue(any("sm_86" in note for note in result["notes"]))

    def test_driver_below_policy_fails_identity(self):
        manifest = fixture_manifest()
        result = TOOL.evaluate_gpu_identity(manifest, "570.194.99", "8.6")
        self.assertFalse(result["ok"])
        self.assertFalse(result["driver_ok"])
        self.assertIn("policy_min_driver", result["detail"])

    def test_arch_below_minimum_fails_identity(self):
        manifest = fixture_manifest()
        result = TOOL.evaluate_gpu_identity(manifest, "571", "7.5")
        self.assertFalse(result["ok"])
        self.assertFalse(result["arch_ok"])

    def test_gpu_smoke_report_records_tested_values_and_policy(self):
        manifest = fixture_manifest()
        probe = {
            "checks": [("nvidia_smi_identity", True, "ok")],
            "gpu_ok": True, "host_ok": True, "nvidia_smi": True, "nvidia_device_node": True,
            "cpu_ready": True, "driver": "571.10", "uuid": "GPU-x", "compute_cap": "8.9",
            "libcuda_realpath": "/usr/local/nvidia/lib64/libcuda.so.1", "cuinit_rc": 0,
            "kernel_values": 1024,
            "identity_policy": TOOL.gpu_identity_policy(manifest),
            "identity_notes": [],
        }
        report = TOOL.build_gpu_smoke_report(manifest, probe)
        self.assertEqual(report["gpu"]["tested"], {"driver": "571.10", "compute_cap": "8.9"})
        self.assertEqual(report["gpu"]["policy"]["min_driver"], "570.195.03")
        self.assertEqual(report["gpu"]["probe_arch"], "sm_86")
        VALIDATOR.validate_doctor_report(report)

    def test_gpu_smoke_always_records_policy_even_without_nvidia_smi(self):
        manifest = fixture_manifest()
        inspector = FakeInspector(ldd={STOCK: healthy_ldd(), SEED: healthy_ldd()})
        with tempfile.TemporaryDirectory() as tmp:
            probe = TOOL.run_gpu_smoke(manifest, inspector, tmp)
        self.assertFalse(probe["gpu_ok"])
        self.assertEqual(probe["identity_policy"]["min_driver"], "570.195.03")
        self.assertEqual(probe["identity_policy"]["supported_arches"], ["8.6", "8.9", "12.0"])


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

    def test_recipe_derives_python_from_installed_interpreter(self):
        text = (ROOT / "dev/Dockerfile.r570").read_text()
        # The toolchain record must not hardcode the interpreter version.
        self.assertIn("python-version.txt", text)
        self.assertIn("/opt/colmap-python/bin/python3.14 --version", text)
        self.assertNotIn('echo "python=3.14.7"', text)
        self.assertIn("COPY --from=python", text)

    def test_build_control_requires_patch_sha(self):
        result = subprocess.run(
            ["bash", str(ROOT / "dev/build-control.sh"), "stock", "/tmp/archive",
             "0" * 64, "/tmp/patch"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("patch requires sha", result.stderr)

    def test_probe_references_match_deployed_filenames(self):
        text = (ROOT / "dev/photogram_dev.py").read_text()
        for name in ("driver_resolve.c", "cuda_launch.cu"):
            self.assertTrue((ROOT / "dev/gpu_probe" / name).is_file())
            self.assertIn(f"gpu-probe/{name}", text)
        # The old hyphenated spellings referenced files that were never deployed.
        self.assertNotIn("gpu-probe/driver-resolve.c", text)
        self.assertNotIn("gpu-probe/cuda-launch.cu", text)


if __name__ == "__main__":
    unittest.main()
