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
  is implied by that static check.
- Source/build trees are `/opt/src/colmap-pr8` and
  `/opt/src/colmap-pr8/build`. Compiler/dependency tools and optional offline
  control helpers remain available; ordinary launcher runs do not invoke them.

The launcher integration belongs to photogram. It must use the digest and baked
binary rather than rebuilding each rental. Phase reruns must clear that phase's
maps: COLMAP silently skips references whose output maps already exist. Killing
only the launcher does not necessarily reap descendants; use governed stage
cleanup or pause/stage-only jobs instead of manual takeover. This image does not
itself repair launcher process/workspace lifecycle bugs.

## Evidence limits

Upstream measurements: measured byte-exact at 1 worker/GPU; 4 workers/GPU
validation in progress. The earlier 4-worker mismatch conclusion was withdrawn
because an orphaned process using another binary contaminated a reused workspace.
Neither byte-exactness nor non-exactness at 4 workers/GPU is established here.

The image's binary SHA256 is computed during this build, not copied from a prior
host benchmark. Workflow artifacts retain that hash and the image digest once
published. Use only for disposable experiments, with no production data, under
the [unchanged-expiry header-only exception](experimental-dev-security-exception.md).
