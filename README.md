# colmap-runtime

GPU-ready PyCOLMAP container with pinned scientific dependencies.

**Status:** a CPU-validated candidate is published. Anonymous pull and offline
imports by digest passed; GPU execution and reconstruction quality remain unvalidated.

```text
ghcr.io/bu5hm4nn/colmap-runtime@sha256:3922f73194629e3f1b9d83b639d03bf8b7188cbec9776706d49dfa9438f64fde
```

This candidate was published from the pre-transfer `bu5hm4nn` namespace and
remains anonymously pullable there; new candidates publish to
`ghcr.io/uncloud-tech/colmap-runtime`. Built from commit
`800cd7d4dd56933c647caedee7eea4210ca22158` in
[workflow run 36315027809](https://github.com/uncloud-tech/colmap-runtime/actions/runs/36315027809).
Later repository changes are not automatically included in this image.

## Build

Use the manually dispatched **Build runtime candidate** GitHub Actions workflow,
leaving `publish` false. Locally, with Docker:

```sh
python3 -m unittest discover -s tests -v
docker build --pull --platform linux/amd64 --progress=plain -t colmap-runtime:candidate image
```

The build context is only `image/`, with an explicit file allowlist. Never include
credentials, datasets, private metadata or SSH keys in that context. Supply any
required authentication externally at runtime.

### benchmark-v4 source build (option C)

The benchmark-v4 lineage needs two MVS CUDA changes the pinned wheel cannot
express: removal of the shared module-scope `__constant__ ref_K/ref_inv_K`
calibration and a per-instance `cudaStream_t` for the four dense kernel launches.
The `pycolmap-builder` stage therefore fetches the pinned COLMAP 4.2.0 tarball
(sha256 `b61731fb…`, commit `be5e2916…`), applies the hash-pinned
`patch_match_cuda.2streams.patch`, builds COLMAP with CUDA for sm_70/75/86/89/120
(the same list as BabelStream) and installs the resulting wheel in place of the
pinned wheel. The patch file is part of the build context and is hash-checked by
the build and by `tests/test_build_contract.py`.

The build is CPU-validated in CI only: nvcc and cmake run without a GPU, so the
image build proves the patched sources compile, not that the kernels produce
correct depth/normal maps or that two workers overlap. That requires the separate
GPU canary and a per-image comparison against a single-worker run.

Source-build integration requirements (covered by the build contract):

- Keep development headers/toolchains in `pycolmap-builder` only. The runtime
  ancestor installs shared-library packages (`libstdc++6`, `libceres4t64`,
  `libopenimageio2.4t64`, etc.), not their `-dev` counterparts. A post-APT
  package-inventory check fails the build if any installed `-dev` package leaks
  into that ancestor, including `linux-libc-dev`/`libc6-dev`/`libstdc++-13-dev`.
  `apt-get upgrade` does not normally install new packages; the check also
  covers dependency changes from the subsequent runtime-library install.
  No holds are used: security updates remain enabled. Rebuilds remain explicitly
  **not bit-identical** (`runtime-lock.json`); record inventories and deploy by
  image digest rather than claiming reproducibility from package holds.

- Install `openimageio-tools` in the builder: Ubuntu's OpenImageIO CMake
  exports reference `/usr/bin/iconvert` and other tools that `libopenimageio-dev`
  alone does not install.
- Create an empty `/usr/include/opencv4`, following COLMAP's Ubuntu CI/docs.
  OpenImageIO exports this include path even though COLMAP does not use its
  OpenCV functionality.
- Set `CC=/usr/bin/gcc CXX=/usr/bin/g++` for the wheel build. scikit-build-core
  otherwise inherits standalone Python's clang compiler preference, but this
  builder uses the GNU toolchain.
- Set only `cmake.define.colmap_DIR=/opt/colmap/share/colmap`, where upstream
  installs `colmap-config.cmake`. Do not replace `CMAKE_PREFIX_PATH` with
  `/opt/colmap`: that overrides scikit-build-core's package discovery and makes
  the pip-installed `pybind11Config.cmake` undiscoverable. Keep the two-stage
  COLMAP install followed by wheel build; neither step bypasses runtime gates.

## Environment

- NVIDIA CUDA 12.9.1 runtime / Ubuntu 24.04, amd64 base pinned by digest.
- CPython 3.14.7 standalone archive pinned by SHA256.
- PyCOLMAP CUDA12 4.2.0 and scientific dependencies pinned by wheel hashes;
  see `image/runtime-lock.json` and `image/requirements.lock`.
- Pinned pip CUDA runtime/curand libraries take precedence over base equivalents.
  Verification records and asserts actual mapped paths, not just search paths.
- Interpreter: `/opt/colmap-runtime/python/bin/python3.14`.
- Runtime manifest: `/opt/colmap-runtime/runtime-manifest.json`.

Ubuntu packages receive security updates at build time. Build-only pip/ensurepip
are removed before the Python runtime is copied into the final image; runtime
package installation is intentionally unavailable. **Rebuilds are not
bit-identical**; use published images by immutable digest. Exact Python and system
package inventories are generated during the build.

### BabelStream host ISA portability

`/usr/local/bin/babelstream` is compiled from pinned BabelStream v5.0 source at
build time. BabelStream's top-level CMake defaults the host release flags to
`-O3 -march=native`, so a build that does not override them silently adopts the
build host's instruction set and can emit AVX-512. That binary then dies with
SIGILL (rc 132) immediately after printing its header on any rented host without
AVX-512 (Broadwell Xeon E5 v4, EPYC Zen2) — it does not fail loudly, it silently
removes the per-device GPU-bandwidth figure from the run. The build pins
`-DRELEASE_FLAGS="-O3;-march=x86-64-v2"` (the SSE4.2 x86-64 baseline that every
amd64 host this launcher rents supports) and, before installing the binary,
disassembles it and fails if AVX-512 indicators (zmm/mask registers or EVEX-only
mnemonics) remain. CUDA device targets (sm_70/75/86/89/120) are unaffected.

## Validation

The build checks package versions, `pip check`, native imports and CUDA build
support. It repeats the import check with networking disabled. Full chained loader
exceptions remain visible in logs. These checks do not establish GPU execution;
the verifier's GPU mode reports device model and driver information only.

The workflow emits a CycloneDX SBOM and vulnerability report and refuses HIGH or
CRITICAL findings. Lower-severity findings remain visible for review; passing does
not imply zero vulnerabilities. An all-layer audit checks a synthetic context
canary and common credential patterns, including files hidden by later layers;
it is not a guarantee against all sensitive content.

## Synthetic GPU check

`scripts/synthetic_canary.py --output /tmp/colmap-canary` generates five small
textured-plane views, runs CUDA feature extraction/matching and dense stereo,
and checks fused geometry against known depth. Run it with the image's Python
interpreter; the output directory must be fresh. It uses known camera poses and
is not a test of SfM pose recovery. A separate worker-process timeout is 300 seconds.
Use `--check-api` for CPU feature extraction, matching, undistortion and dense-option
validation against the installed bindings. This mode explicitly does not certify
GPU execution. The GPU path has not yet been validated.

## Deployment

The image has no SSH host keys and does not start SSH automatically. Configure
startup explicitly if SSH is needed, generating unique host keys with
`ssh-keygen -A` and providing authorized keys externally. Use a writable CUDA cache
directory when needed. Compatibility with the host driver and GPU must be tested
on the intended system.

## Candidate publication

Publication is manual: enable `publish` and, after reviewing the notices, explicitly
confirm `accept_redistribution_terms`. Both default to false. The workflow publishes
only after its CPU, layer-audit and security gates pass, using a unique candidate
tag. It records the digest, verifies anonymous access and repeats verification
against that digest. A new GHCR package may need its visibility set to public by
the repository owner. A pushed but private package is not considered ready.

Candidates remain GPU-unvalidated until an actual GPU test passes. Registry login
uses only the workflow's short-lived token; it authenticates the registry build
cache and the gated publish and is never written into the image.

### Build cache

The candidate build uses BuildKit with a registry cache stored in a separate,
public package (`ghcr.io/<owner>/colmap-runtime-buildcache:buildcache`,
`mode=max`), so the pinned COLMAP/BabelStream compile layers are reused instead
of rebuilt every run. `--provenance`/`--sbom` are disabled so the loaded image
stays a single-manifest archive for `scripts/audit_image.py`, and the build never
pushes - publication stays behind the security gate.

The base stage consumes a weekly-changing `APT_REFRESH` build argument, so the
shipped Ubuntu packages are re-resolved at least weekly; the build-only
`pycolmap-builder`/`babelstream` stages (which do not ship) stay cached.
Publication adds `--no-cache`, so a published image is always built from current
packages. Each run records the cache-hit count and the BuildKit builder identity
in the evidence artifact, so silent cache degradation is visible.
Package-write permission is job-wide, not isolated to the publication step.
A failed anonymous-access check leaves the pushed candidate in the registry;
it does not roll back the push or establish public deployability.

## Third-party software

Dependencies retain their own licences, including NVIDIA CUDA redistribution
conditions. See `image/THIRD_PARTY_NOTICES.md`. Publication requires publisher acknowledgement of those conditions and passing
security gates. This repository does not relicense
third-party binaries.

## License

This repository's own source code is licensed under the MIT License; see
[`LICENSE`](LICENSE). Third-party components, including those redistributed in
the container image, are not relicensed and remain under their own terms; see
[Third-party software](#third-party-software) and `image/THIRD_PARTY_NOTICES.md`.
