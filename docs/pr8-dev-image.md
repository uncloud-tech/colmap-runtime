# Baked PR8 benchmark image

The dev recipe pins `uncloud-tech/colmap` PR8 at
`340f78310590cefda7cd3bb61ff0775ae5e2b59f`, archive SHA256
`350f219ff4c07f68a9a834e0838d280d1a7f45884e0aa97182229401fe58695e`.
The `Build dev image (PR#8 memory stack)` workflow builds and verifies the
image, retaining existing CPU, architecture, SBOM and security publication gates.
Publication is opt-in and uses a unique `pr8-<workflow-sha>-<run>-<attempt>` tag
in `ghcr.io/uncloud-tech/colmap-runtime-dev`; consume its immutable digest.

## Launcher contract

- Invoke the already installed `/opt/colmap-pr8/bin/colmap`, also first on PATH
  as `colmap`. No source transfer or COLMAP compilation is required on rentals.
- `/opt/colmap-dev/image-contract.json` records the source pin, actual baked
  binary SHA256, binary path, architectures and runtime options. The manifest
  records that binary SHA256 too. `/opt/colmap-dev/colmap.sha256` can be checked
  with `sha256sum -c`; the entrypoint checks it before executing commands.
  The launcher must compare the contract/source/hash with its job expectations;
  an image digest or binary identity mismatch must stop the run, not trigger a
  fallback rebuild or manual takeover.
- `--PatchMatchStereo.sweep_tile` remains a runtime option: 32 (upstream
  default), 16, 8, or 0 (automatic). No tile-specific compiler flag is added.
  Pass the selected value on each governed run, including the N=4 tile sweep.
- `COLMAP_PATCH_MATCH_COMPACT_PRNG=0` by default. B2b requires explicit `=1`
  and upstream additionally restricts it to seed-0 geometric runs. It is
  benchmark-only, not an image-wide default.
- Global CUDA targets: `89-real;120-real`. The upstream NVCC Blackwell
  workaround emits **sm89 SASS + compute90 PTX** for MVS; it deliberately does
  not emit sm120 MVS SASS. The workflow matches every MVS SASS kernel entry
  against compute90 PTX per object. No GPU execution or driver-JIT validation
  is implied by that static check. The pinned source attributes the workaround
  to NVCC native sm100+ miscompilation at -O2/-O3 (upstream issue #3514); this
  image does not patch or bypass it. The global architecture list alone is not
  proof of native sm120 MVS code.
- Source/build trees are `/opt/src/colmap-pr8` and
  `/opt/src/colmap-pr8/build`. Compiler/dependency tools and optional offline
  control helpers remain available; ordinary launcher runs do not invoke them.

The launcher integration belongs to photogram. It must use the digest and baked
binary rather than rebuilding each rental. Phase reruns must clear that phase's
maps: COLMAP silently skips references whose output maps already exist. Killing
only the launcher does not necessarily reap descendants; use governed stage
cleanup or pause/stage-only jobs instead of manual takeover. This image does not
itself repair launcher process/workspace lifecycle bugs.

## Shared pinned Python layer (validation-only)

`dev/python/Dockerfile` layers on the exact native parent
`ghcr.io/uncloud-tech/colmap-runtime-dev@sha256:8993096b761a11d210afc5c49cbc8b8622d0b96d36fb539b348089c18d97ac0b`.
It does not compile native COLMAP or change its configuration/libraries.
The one shared installation is `/opt/colmap-python`, CPython `3.14.7+20260924`
with the exact 16 historical wheels plus bundled pip 26.2.1. `python` and
`python3` in `/usr/local/bin` resolve to that interpreter; `/usr/bin` is untouched.
Jobs may reuse it or create scratch-owned venvs without modifying the baseline.
Benchmarks explicitly select `/opt/colmap-python/bin/python3.14 -E -s -B JOB/scripts/run.py`.
No global PATH/LD_LIBRARY_PATH change or Python CUDA library injection is made.

The original lock remains byte-identical under the prefix and refers to the
**native parent**, not a derived registry digest. Schema 2 adds a Python identity
and hashes the complete runtime/file manifest; the strict native projection is
still schema 1. Read-only/no-network container verification checks offline package
closure, synthetic CPU preparation, native before/after source/tool/library hashes,
loaded wheel-local cudart/curand paths and a disposable offline venv.

Dispatch the registered build-dev workflow with `runtime_layer=python`,
`publish=false` only under explicit CI/build authority. The native job is skipped;
the Python job has read-only repository permissions and no registry/cache export.
It saves the **actual image**, gzip-split in 1 GiB parts with SHA256SUMS, as
`python-layer-image-<run-id>` (1-day retention), plus checksummed verification
`python-layer-evidence-<run-id>` (14 days). Restore by checking SHA256SUMS,
concatenating parts, decompressing and `docker load`; compare the resulting image
ID with `image-id.txt`. Failed post-build gates still retain the candidate but do
not make it ready. No image artifact exists if the build itself failed.

This does not update the frozen coordinator's interpreter/library selection;
photogram owns that separate handoff. GPU/MPS/632-map correctness remains pending.
No new registry digest is asserted by validation-only image retention.

## Evidence limits

Upstream measurements: measured byte-exact at 1 worker/GPU; 4 workers/GPU
validation in progress. The earlier 4-worker mismatch conclusion was withdrawn
because an orphaned process using another binary contaminated a reused workspace.
Neither byte-exactness nor non-exactness at 4 workers/GPU is established here.
The image does not inherit those upstream results. It requires a fresh
reference-map gate (the commissioned 632-map comparison) against its actual
binary on the target GPU/driver before asserting numerical correctness. Both
manifest and contract record `mvs_codegen_policy=upstream_blackwell_ptx_workaround`,
`gpu_execution_validated=false`, `byte_exactness_inherited=false`, and
`required_gpu_validation=fresh_reference_map_gate` (booleans in JSON, textual
values in the manifest). PTX-JIT compatibility is not a byte-exactness guarantee.

The image's binary SHA256 is computed during this build, not copied from a prior
host benchmark. Workflow artifacts retain that hash and the image digest once
published. Use only for disposable experiments, with no production data, under
the [unchanged-expiry header-only exception](experimental-dev-security-exception.md).
