import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BuildContractTests(unittest.TestCase):
    def test_base_is_amd64_digest_pinned(self):
        lock = json.loads((ROOT / "image/runtime-lock.json").read_text())
        self.assertRegex(lock["base"], r"^nvidia/cuda@sha256:[a-f0-9]{64}$")
        self.assertEqual(lock["platform"], "linux/amd64")
        self.assertEqual(lock["python"]["version"], "3.14.7")

    def test_dockerfile_matches_lock(self):
        lock = json.loads((ROOT / "image/runtime-lock.json").read_text())
        dockerfile = (ROOT / "image/Dockerfile").read_text()
        self.assertIn("FROM " + lock["base"], dockerfile)
        self.assertIn(lock["python"]["url"], dockerfile)
        self.assertIn(lock["python"]["sha256"], dockerfile)
        self.assertNotIn("CUDA_CACHE_DISABLE=1", dockerfile)
        # The base stage bounds apt-layer reuse with a weekly build argument.
        self.assertIn("ARG APT_REFRESH", dockerfile)
        self.assertIn("APT_REFRESH=${APT_REFRESH}", dockerfile)
        self.assertFalse(lock["rebuild_bit_identical"])

    def test_image_does_not_break_vast_ssh_bootstrap(self):
        """Incident 2026-09-28: deleting the SSH host keys made Vast's `sshd` start
        fail ("no hostkeys available -- exiting") and its port-forward never
        recovered, so readiness polling saw `connection refused` for the whole
        window. A stock Ubuntu + openssh-server install ships host keys; the image
        must not deviate from that."""
        dockerfile = (ROOT / "image/Dockerfile").read_text()
        for forbidden in (
            "rm -f /etc/ssh/ssh_host",
            "rm -rf /etc/ssh/ssh_host",
            "ssh-keygen -R",
            "PasswordAuthentication yes",
        ):
            self.assertNotIn(forbidden, dockerfile)
        self.assertIn("openssh-server", dockerfile)
        self.assertIn("mkdir -p /run/sshd", dockerfile)
        # The platform starts sshd from the image at container start and does not
        # generate host keys at runtime, so they must exist in the image.
        self.assertIn("ssh-keygen -A", dockerfile)
        # ...and the audit must tolerate exactly those host key paths, no more.
        audit = (ROOT / "scripts/audit_image.py").read_text()
        self.assertRegex(audit, r"""["']etc/ssh/ssh_host_rsa_key["'],""")
        self.assertIn("SSH_HOST_KEY_PATHS", audit)
        # Host keys must exist at build time. `ssh-keygen -A` is the safe
        # "generate every missing host-key type" command; a bare delete leaves
        # the image keyless and Vast's sshd then exits on first start.
        # The platform starts sshd from the image at container start and does not
        # generate host keys at runtime, so the image must ship them.
        self.assertIn("ssh-keygen -A", dockerfile)
        self.assertNotIn("/etc/init.d/ssh", dockerfile)
        audit = (ROOT / "scripts/audit_image.py").read_text()
        self.assertIn("SSH_HOST_KEY_PATHS", audit)

    def test_babelstream_is_pinned_and_installed(self):
        """A measured GPU bandwidth figure must come from a pinned, proven tool.

        BabelStream v5.0's CUDA model ignores CMAKE_CUDA_ARCHITECTURES: it
        requires CUDA_ARCH and CMAKE_CUDA_COMPILER and emits one nvcc -arch=
        (src/cuda/model.cmake). The other rented GPU families must therefore be
        added as explicit --generate-code entries, or the binary only runs on
        one architecture.
        """
        dockerfile = (ROOT / "image/Dockerfile").read_text()
        self.assertIn(
            "63aab1bc42a1e953dcae26e279ab100866f8491ab5ce7167269f2ca4b16bb2fb",
            dockerfile,
        )
        self.assertIn("UoB-HPC/BabelStream/tarball/v5.0", dockerfile)
        self.assertIn(
            "nvidia/cuda@sha256:020bc241a628776338f4d4053fed4c38f6f7f3d7eb5919fecb8de313bb8ba47c",
            dockerfile,
        )
        self.assertIn("sha256sum -c -", dockerfile)
        self.assertIn(
            "COPY --from=babelstream /usr/local/bin/babelstream /usr/local/bin/babelstream",
            dockerfile,
        )
        # BabelStream's own required flags, not CMake's ignored CMAKE_CUDA_ARCHITECTURES.
        # Scope the check to the BabelStream configure block: the separate
        # pycolmap source-build stage below does use CMAKE_CUDA_ARCHITECTURES.
        babel_configure = dockerfile[
            dockerfile.index("cmake -S source -B build") : dockerfile.index(
                "objdump -d build/cuda-stream"
            )
        ]
        self.assertIn("-DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc", babel_configure)
        self.assertNotIn("-DCMAKE_CUDA_ARCHITECTURES", babel_configure)
        # Every rented family must have native code: Ampere, Ada and Blackwell.
        # Ampere comes from -DCUDA_ARCH=sm_86 (which also embeds compute_86 PTX);
        # the other two are explicit --generate-code entries.
        self.assertIn("-DCUDA_ARCH=sm_86", dockerfile)
        self.assertIn("code=sm_89", dockerfile)
        self.assertIn("code=sm_120", dockerfile)
        # Volta and Turing too: the campaign rents V100 (900 GB/s HBM2) and T4
        # hosts, and CUDA 12.9 still supports building for both. Without these the
        # measured bandwidth figure is absent on those hosts.
        self.assertIn("code=sm_70", dockerfile)
        self.assertIn("code=sm_75", dockerfile)
        # v5.0 compiles `$(MODEL)-stream`, so the CUDA binary is build/cuda-stream.
        self.assertIn(
            "install -m 0755 build/cuda-stream /usr/local/bin/babelstream", dockerfile
        )
        self.assertNotIn("-name babelstream", dockerfile)
        self.assertNotIn("-arch=native", dockerfile)
        self.assertIn(
            "BabelStream", (ROOT / "image/THIRD_PARTY_NOTICES.md").read_text()
        )

    def test_babelstream_host_isa_is_portable(self):
        """Incident 2026-09-29: the published a9d97999 babelstream SIGILLed
        (rc 132) right after its header on hosts without AVX-512 (Broadwell
        Xeon E5 v4, EPYC 7452/7532 Zen2), silently dropping the GPU-bandwidth
        figure. BabelStream v5.0's top-level CMakeLists.txt sets
        `DEFAULT_RELEASE_FLAGS -O3 -march=native` (line 49), so an unpinned
        build inherits the GitHub runner's AVX-512 host ISA. The build must
        override that with a portable baseline and assert the produced binary."""
        dockerfile = (ROOT / "image/Dockerfile").read_text()
        # BabelStream's documented override for DEFAULT_RELEASE_FLAGS, pinned to
        # the SSE4.2 x86-64 baseline instead of `-march=native`.
        self.assertIn('-DRELEASE_FLAGS="-O3;-march=x86-64-v2"', dockerfile)
        # No `-march=native` may survive in the cmake configure command.
        configure = dockerfile[
            dockerfile.index("cmake -S source -B build") : dockerfile.index(
                "objdump -d build/cuda-stream"
            )
        ]
        self.assertNotIn("-march=native", configure)
        # The produced host code must be checked, and the check must run before
        # the binary is installed, so a failing build never lands in the image.
        self.assertIn(
            "objdump -d build/cuda-stream > build/cuda-stream.disassembly", dockerfile
        )
        self.assertLess(
            dockerfile.index("objdump -d build/cuda-stream"),
            dockerfile.index("install -m 0755 build/cuda-stream"),
        )

    def _babelstream_isa_guard_pattern(self):
        dockerfile = (ROOT / "image/Dockerfile").read_text()
        match = re.search(r"grep -Eq '([^']+)'", dockerfile)
        self.assertIsNotNone(
            match, "the babelstream ISA guard must be present in the Dockerfile"
        )
        return match.group(1)

    def test_babelstream_isa_guard_detects_avx512(self):
        """The build-time guard must actually flag AVX-512 host code while
        passing a portable x86-64-v2 build, so the assertion is meaningful and
        not cosmetic. Skipped where a host toolchain is unavailable; the Docker
        build stage always installs one (g++ pulls in objdump)."""
        if not (shutil.which("g++") and shutil.which("objdump")):
            self.skipTest("g++/objdump not available")
        pattern = self._babelstream_isa_guard_pattern()
        samples = {
            "avx512": (
                "#include <immintrin.h>\n"
                '__attribute__((target("avx512f")))\n'
                "void f512(float *a, float *b) {\n"
                "  __m512 x = _mm512_loadu_ps(a);\n"
                "  __m512 y = _mm512_loadu_ps(b);\n"
                "  _mm512_storeu_ps(a, _mm512_add_ps(x, y));\n"
                "}\n",
                True,
            ),
            "portable": (
                "int f(const int *a, int n) { int s = 0; for (int i = 0; i < n; i++) s += a[i] * 3; return s; }\n",
                False,
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for label, (source, expect_hit) in samples.items():
                src = Path(tmp) / f"{label}.c"
                obj = Path(tmp) / f"{label}.o"
                src.write_text(source)
                try:
                    subprocess.run(
                        [
                            "g++",
                            "-O3",
                            "-march=x86-64-v2",
                            "-c",
                            str(src),
                            "-o",
                            str(obj),
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                except (OSError, subprocess.CalledProcessError) as exc:
                    self.skipTest(f"cannot compile the {label} sample: {exc}")
                disassembly = subprocess.run(
                    ["objdump", "-d", str(obj)],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                self.assertEqual(
                    bool(re.search(pattern, disassembly)),
                    expect_hit,
                    f"{label} sample: guard match expected to be {expect_hit}",
                )

    def test_babelstream_isa_guard_fails_closed_under_pipefail(self):
        """Exercise the Docker RUN guard, including large-output SIGPIPE cases."""
        if not all(shutil.which(tool) for tool in ("g++", "objdump", "bash")):
            self.skipTest("g++/objdump/bash not available")
        dockerfile = (ROOT / "image/Dockerfile").read_text()
        start = dockerfile.index(' && cmake --build build -j"$(nproc)"')
        start = dockerfile.index("\n", start) + 1
        end = dockerfile.index(" && install -m 0755 build/cuda-stream", start)
        # Execute the actual guard with the stage's shell semantics. Replace only
        # the following installation with a marker; never install a test object.
        command = "true \\\n" + dockerfile[start:end] + " && echo ACCEPTED"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "build").mkdir()
            source = root / "fixture.s"
            binary = root / "build/cuda-stream"
            for case in ("avx512", "portable", "grep_failure", "objdump_failure"):
                with self.subTest(case=case):
                    if case == "objdump_failure":
                        binary.unlink()
                    else:
                        instruction = (
                            "vpxord %zmm0, %zmm0, %zmm0\n" if case == "avx512" else ""
                        )
                        # A match near the start must not terminate the producer
                        # while it still has more than a pipe buffer to write.
                        source.write_text(
                            ".text\n.globl fixture\nfixture:\n"
                            + instruction
                            + ".rept 100000\n nop\n.endr\n ret\n"
                        )
                        subprocess.run(
                            ["g++", "-c", str(source), "-o", str(binary)],
                            check=True,
                            capture_output=True,
                            text=True,
                        )
                    prefix = "grep() { return 2; }; " if case == "grep_failure" else ""
                    result = subprocess.run(
                        ["bash", "-o", "pipefail", "-c", prefix + command],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if case == "portable":
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn("ACCEPTED", result.stdout)
                    else:
                        self.assertNotEqual(result.returncode, 0, result.stdout)
                        self.assertNotIn("ACCEPTED", result.stdout)

    def test_requirements_match_locked_hashes(self):
        lock = json.loads((ROOT / "image/runtime-lock.json").read_text())
        lines = [
            line
            for line in (ROOT / "image/requirements.lock").read_text().splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(len(lines), len(lock["wheels"]))
        for wheel in lock["wheels"]:
            self.assertIn(
                f"{wheel['name']}=={wheel['version']} --hash=sha256:{wheel['sha256']}",
                lines,
            )

    def test_pycolmap_is_source_built_from_pinned_patch(self):
        """benchmark-v4 option C needs kernel surgery, so pycolmap is rebuilt
        from a hash-pinned COLMAP 4.2.0 tarball with a hash-pinned patch instead
        of installed from the immutable wheel. The build must verify both before
        configuring, apply the patch before CMake, and target every rented GPU
        family."""
        import hashlib

        lock = json.loads((ROOT / "image/runtime-lock.json").read_text())
        dockerfile = (ROOT / "image/Dockerfile").read_text()
        requirements = (ROOT / "image/requirements.lock").read_text()
        self.assertNotIn("pycolmap-cuda12", requirements)
        builds = {build["name"]: build for build in lock["source_builds"]}
        build = builds["pycolmap"]
        self.assertEqual(build["version"], "4.2.0")
        self.assertEqual(build["commit"], "be5e29168d4aff238409d60424812df66aac919f")
        self.assertIn(build["sha256"], dockerfile)
        self.assertIn(build["patch_sha256"], dockerfile)
        patch = (ROOT / "image/patch_match_cuda.2streams.patch").read_bytes()
        self.assertEqual(hashlib.sha256(patch).hexdigest(), build["patch_sha256"])
        # The verified tarball and patch must be applied before CMake configures.
        self.assertLess(
            dockerfile.index("sha256sum -c /tmp/sums"),
            dockerfile.index(
                "patch -d source -p1 < /build/patch_match_cuda.2streams.patch"
            ),
        )
        self.assertLess(
            dockerfile.index(
                "patch -d source -p1 < /build/patch_match_cuda.2streams.patch"
            ),
            dockerfile.index("cmake -S source -B source/build"),
        )
        self.assertIn("-DCUDA_ENABLED=ON", dockerfile)
        self.assertIn('-DCMAKE_CUDA_ARCHITECTURES="70;75;86;89;120"', dockerfile)
        self.assertIn("-DBUILD_SHARED_LIBS=OFF", dockerfile)
        # Ubuntu's OpenImageIO CMake config validates imported executable targets
        # (/usr/bin/iconvert, ...) and hardcodes the OpenCV include dir in the
        # OIIO interface; the builder must install openimageio-tools and create
        # the empty opencv4 include dir or COLMAP's configure fails.
        self.assertIn("openimageio-tools", dockerfile)
        self.assertIn("mkdir -p /usr/include/opencv4", dockerfile)
        # Development packages must never enter a runtime ancestor layer.
        base = dockerfile.split("AS pycolmap-builder", 1)[0]
        installs = base.split("apt-get install", 1)[1].split("&&", 1)[0]
        self.assertNotIn("-dev", installs)
        self.assertIn("libstdc++6", installs)
        self.assertIn("libceres4t64", installs)
        self.assertIn("libopenimageio2.4t64", installs)
        self.assertIn("ERROR: runtime development package:", base)
        # Keep backend-provided package discovery intact; only locate COLMAP.
        wheel_step = dockerfile.split("RUN mkdir -p /opt/wheels &&", 1)[1].split(
            "FROM base AS builder", 1
        )[0]
        self.assertIn("CC=/usr/bin/gcc CXX=/usr/bin/g++", wheel_step)
        self.assertIn(
            "--config-settings=cmake.define.colmap_DIR=/opt/colmap/share/colmap",
            wheel_step,
        )
        self.assertNotIn("cmake.define.CMAKE_PREFIX_PATH=", wheel_step)
        # The source-built wheel replaces the pinned wheel in the runtime stage.
        self.assertIn("pycolmap==4.2.0", dockerfile)
        self.assertIn("COPY --from=pycolmap-builder /opt/wheels/", dockerfile)
        self.assertIn("source_builds", (ROOT / "image/verify_runtime.py").read_text())

    def test_build_context_is_allowlisted(self):
        ignore = (ROOT / "image/.dockerignore").read_text().splitlines()
        self.assertEqual(ignore[0], "**")
        self.assertEqual(
            set(ignore[1:]),
            {
                "!Dockerfile",
                "!runtime-lock.json",
                "!requirements.lock",
                "!verify_runtime.py",
                "!THIRD_PARTY_NOTICES.md",
                "!patch_match_cuda.2streams.patch",
            },
        )
        dockerfile = (ROOT / "image/Dockerfile").read_text()
        self.assertNotIn("COPY . ", dockerfile)
        self.assertNotIn("COPY ..", dockerfile)
        self.assertIn("pip check", dockerfile)
        self.assertIn("verify_runtime.py --mode cpu", dockerfile)

    def test_publication_requires_terms_and_follows_security_checks(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        self.assertIn("accept_redistribution_terms:", workflow)
        self.assertIn("packages: write", workflow)
        self.assertLess(
            workflow.index("scripts/check_security.py"), workflow.index("docker push")
        )
        self.assertIn('docker --config "$anonymous" manifest inspect', workflow)
        self.assertIn(
            "candidate-${GITHUB_SHA}-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}", workflow
        )

    def test_workflow_does_not_publish_by_default(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("if: inputs.publish", workflow)
        # BuildKit path: pinned setup action, registry cache, single-manifest
        # load, and a build that never pushes (publication stays gated).
        self.assertIn("useblacksmith/setup-docker-builder@", workflow)
        self.assertIn("docker buildx build", workflow)
        self.assertIn("--pull", workflow)
        self.assertIn("--provenance=false --sbom=false", workflow)
        self.assertIn("type=registry,ref=", workflow)
        self.assertIn("mode=max", workflow)
        self.assertIn("-buildcache:buildcache", workflow)
        self.assertIn("APT_REFRESH", workflow)
        self.assertIn("--no-cache", workflow)
        self.assertIn(" image", workflow)
        self.assertNotIn("--push", workflow)
        self.assertNotIn("pull_request_target", workflow)

    def test_blacksmith_migration_keeps_pins_and_separate_caches(self):
        for filename, cpus, cache in [
            ("build.yml", 4, "runtime"),
            ("build-dev.yml", 32, "dev"),
        ]:
            with self.subTest(workflow=filename):
                workflow = (ROOT / ".github/workflows" / filename).read_text()
                self.assertIn(f"runs-on: blacksmith-{cpus}vcpu-ubuntu-2404", workflow)
                self.assertRegex(workflow, r"uses: actions/checkout@[0-9a-f]{40}\b")
                self.assertRegex(
                    workflow, r"uses: useblacksmith/setup-docker-builder@[0-9a-f]{40}\b"
                )
                self.assertNotIn("useblacksmith/checkout@", workflow)
                self.assertIn("persist-credentials: false", workflow)
                self.assertIn("cache-key: ${{ github.repository }}/" + cache, workflow)
                self.assertIn("nofallback: true", workflow)
                self.assertIn("buildx-version: v0.37.2", workflow)
                self.assertIn("docker buildx build", workflow)
                self.assertIn("--load", workflow)
                self.assertIn("type=registry,ref=$cache_ref", workflow)
                self.assertIn("mode=max", workflow)
                self.assertNotIn("--push", workflow)
                self.assertIn("cancel-in-progress: false", workflow)
                self.assertNotIn("pull_request:", workflow)
                self.assertNotIn("pull_request_target:", workflow)


if __name__ == "__main__":
    unittest.main()
