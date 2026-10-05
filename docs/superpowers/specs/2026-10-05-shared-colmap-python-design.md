# Shared pinned Python for the experimental COLMAP dev image

**Status:** revised arrangement approved; this written design awaits owner review and design/implementation handoff approval. Implementation remains paused. This document grants no CI dispatch, image build, Git push, registry publication, PR opening, GPU rental, or coordinator integration authority.

## 1. Intent and scope

Provide one reusable image Python installation containing the complete historical benchmark environment. The frozen dev-sweep preflight imports PyCOLMAP before the launcher provisions its wheelhouse; the baked runtime makes those dependencies available before provisioning when the coordinator selects it, without another per-rental installation.

The installation is shared image infrastructure, **not benchmark-private**. Benchmarks select it explicitly and verify its identity; other jobs can use the same installation or create their own virtual environments. The image must not carry a second Python installation merely to isolate the benchmark.

The change adds Python and its locked wheels to the existing immutable native image. It does not rebuild COLMAP, change its toolchain/libraries, alter benchmark science, or implement launcher recovery, timeout cleanup, disk salvage, guardian retention, or rental behavior. Photogram owns separately approved job/launcher integration; no frozen coordinator tree is edited here.

## 2. Verified parent and duplication assessment

Native parent:

```text
ghcr.io/uncloud-tech/colmap-runtime-dev@sha256:8993096b761a11d210afc5c49cbc8b8622d0b96d36fb539b348089c18d97ac0b
```

Its verified configuration/image ID is:

```text
sha256:8e5cf68891c363387978f630221cbb112b3c788a25247c7e1026bb335049b23e
```

The owner-approved, one-time inspection ran on `linux/amd64`, with a read-only root filesystem, no container networking, and dropped capabilities:

- Branch `ci/inspect-pr8-parent`, commit `7ca825cdf542828012e1623f17db73d66ad1ad2e`.
- [Run 37311457837](https://github.com/uncloud-tech/colmap-runtime/actions/runs/37311457837), successful; native build job skipped.
- Artifact `parent-python-inspection-37311457837`, downloaded checksums independently verified.
- No interpreter found through PATH checks for `python`, `python3`, `python3.14`, `pypy`, or `pypy3`, or named interpreter searches in `/usr/bin`, `/bin`, `/usr/local`, `/usr/lib`, and `/opt`, to depth 8.
- No `site-packages` or `dist-packages` directories found in that scope. No present interpreter version, pip executable, or installed Python distribution inventory could therefore be reported.
- Earlier exact-image inventories independently contained no Python/PyPI package entries (575 dpkg records; 576 SBOM components).

These are observations of the immutable image, not an inference from the Dockerfile or the launcher's interpreter selection. They do not assert absence of every arbitrarily named executable outside the inspected scope. **No reusable exact locked interpreter was found**; adding the proposed runtime does not duplicate a discovered system Python. Inspection authority was consumed by that one run and is not standing CI permission.

## 3. Runtime interface

| Interface | Decision |
| --- | --- |
| Shared installation prefix | `/opt/colmap-python` |
| Explicit interpreter | `/opt/colmap-python/bin/python3.14` |
| Unversioned command | `/usr/local/bin/python` symlink to that same interpreter |
| Python 3 command | `/usr/local/bin/python3` symlink to that same interpreter |
| System interpreter paths | Do not add or replace `/usr/bin/python*` |
| Shared site-packages | `/opt/colmap-python/lib/python3.14/site-packages` |
| Environment lock | `/opt/colmap-python/environment-lock.json` |
| Runtime evidence | `/opt/colmap-python/runtime-manifest.json` |
| Native executable | Unchanged `/opt/colmap-pr8/bin/colmap` |

All image-level aliases must resolve to the one installed interpreter. No private `/opt/colmap-benchmark/python` runtime is created, and no benchmark-relative `installed/python` tree is baked. Python archive-internal aliases may be retained if they resolve to the same interpreter.

The image's existing PATH string is preserved: `/usr/local/bin` is already in it, so the new aliases require no global PATH rewrite. The native COLMAP binary remains first on PATH. Bootstrap tooling stays under the shared prefix; there is no requirement to add unversioned global pip commands.

Benchmarks invoke:

```text
/opt/colmap-python/bin/python3.14 -E -s -B JOB/scripts/run.py ...
```

This preserves script-local imports, ignores Python environment-variable overrides and the user site, and avoids bytecode writes. It is deliberately not `-I` for workload scripts that need neighboring `science` modules. Offline installer/module checks may use `-I` separately.

Other jobs may use `python`/`python3`, or create job-owned virtual environments. No virtual environment is baked into the image as a second interpreter. Jobs needing additions or different versions must not mutate the shared benchmark baseline; their dependency installation/provisioning needs its own job authority. The shipped ensurepip supports offline venv bootstrap without adding an uncontrolled installer download.

## 4. Exact public inputs and offline installation

Authoritative input is the coordinator's complete lock, preserved byte-for-byte:

```text
environment-lock.json SHA256:
a22ac04ee8febc9f46f281d7b01d200e73e75f2d380bbc02b0bffc4992ee45cd
```

The lock is available locally as `dev/python/environment-lock.json`, copied from `photogram/out/dev-image-sweep-readiness/prepared-r4-frozen/environment-lock.json`. It contains only the public runtime/wheel manifest and the native parent digest. Its 17 artifacts total **258,592,337 bytes**. All supplied cached artifact sizes/hashes and the extracted interpreter hash were checked read-only; cached bytes are not evidence of container installation.

Interpreter:

- CPython `3.14.7+20260924`, official Astral python-build-standalone release archive.
- Archive SHA256 `bd0d0568ccded07bbf1c87727230dc5dd0187e706a87da23c4de78388a229b78`.
- Installed interpreter ELF must retain SHA256 `5a91882290532b2719eaca77c0f3a7448bd73b9214e56df57bc59004560a80c6` after relocation into the shared prefix.
- The archive contains pip **26.2.1**, including the bundled ensurepip wheel. Retain and record this bootstrap identity; do not fetch newer pip, setuptools, or wheel.

The exact 16 locked distributions are:

| Distribution | Version |
| --- | --- |
| contourpy | 1.4.0 |
| cuda-toolkit | 12.9.2.0 |
| cycler | 0.12.1 |
| fonttools | 4.65.0 |
| kiwisolver | 1.5.1 |
| matplotlib | 3.11.2 |
| numpy | 2.5.3 |
| nvidia-cuda-runtime-cu12 | 12.9.79 |
| nvidia-curand-cu12 | 10.3.10.19 |
| packaging | 26.3 |
| pillow | 12.3.0 |
| pycolmap-cuda12 | 4.2.0 |
| pyparsing | 3.3.2 |
| python-dateutil | 2.9.0.post0 |
| scipy | 1.18.1 |
| six | 1.17.0 |

These are historical comparison inputs, not a latest-stable recommendation. Full filenames, official public URLs, lengths, and individual SHA256 values remain in the authoritative lock; do not re-resolve versions, change wheel tags, or select source distributions. Selected PyCOLMAP CUDA dependencies are covered by the locked runtime/curand wheels; do not request the CUDA toolkit's `all` extra.

The intended acquisition boundary downloads only the lock's official public URLs, verifies size/hash and wheel metadata/tag/name/version, and produces a confined build context. Installation runs with networking disabled, bundled ensurepip, and pip's `--isolated --no-index --no-deps --require-hashes --only-binary=:all:` controls. `pip check` and a complete installed-distribution inventory must pass. The shared prefix must contain exactly the locked distributions plus the recorded bundled bootstrap tooling; unexpected additions require investigation.

A missing Python dependency, OS library, ABI requirement, or licensing notice is a reported blocker, not authority for an apt install, new artifact, dependency upgrade, or alternate interpreter. Keep runtime/wheel license notices and redistribution evidence. Public download availability alone does not establish redistribution permission.

## 5. Native preservation and library isolation

Layer on the exact native parent digest without native recompilation, apt operations, toolchain replacement, native source changes, or native artifact copying from another build. The final image contains only the new shared runtime, aliases, and its evidence/contract updates above the parent.

Preserve:

- COLMAP source commit `340f78310590cefda7cd3bb61ff0775ae5e2b59f`.
- `/opt/colmap-pr8/bin/colmap` SHA256 `fc896cb9b6a5883285673a6cd1c21d768c5a2d554d7c52748a6ae63aeb59e34c`.
- CUDA 12.8 native toolchain/libraries, `/opt/deps`, source/build tree, native executable settings and checksum-checking entrypoint.
- Global CUDA targets `89-real;120-real`; MVS targets `89-real;90-virtual` under the unmodified upstream Blackwell PTX workaround.
- Runtime `--PatchMatchStereo.sweep_tile` specializations and compact PRNG default `0`.
- Global `LD_LIBRARY_PATH=/opt/deps/lib:/opt/colmap-pr8/lib`, as observed in the exact parent. Do not globally inject the Python wheel CUDA library directories or alter the loader cache.

The PyCOLMAP wheel's inspected initializer preloads its wheel-provided cudart/curand libraries by their filesystem paths. The Python environment can therefore have its locked CUDA 12.9 libraries without replacing native COLMAP's CUDA 12.8 resolution. This is a design hypothesis supported by the wheel code, **not yet a verified container import result**. Verify actual loaded paths/library hashes in the Python process and separately verify native resolution after installation. If extra loader settings are needed, stop for design review rather than add a global library override.

Record native `ldd` resolution, canonical library paths, and library-byte hashes before/after. Ignore ASLR addresses when comparing; paths and hashes are the comparison. Record source/toolchain/dependency identities and package inventory sufficiently to show the native environment did not change. The inspection observed native `libcudart.so.12` resolving to `/usr/local/cuda/targets/x86_64-linux/lib/libcudart.so.12`; retain that baseline.

## 6. Contracts affected

### Image-side contracts

1. **`/opt/colmap-dev/image-contract.json`:** introduce a distinct schema version 2 for the Python-equipped image, retaining the parent contract's native field values (the schema discriminator itself changes from 1 to 2). Add `native_parent_digest`, `environment_lock_sha256`, and a `python` object describing the shared prefix, explicit interpreter, command aliases, archive release/hash, executable version/hash, bootstrap identity, installed-distribution manifest path/hash, and library environment/evidence. Native fields are not repurposed to identify Python.
2. **`/opt/colmap-dev/BUILD-MANIFEST.txt`:** preserve existing native records and append clearly Python-prefixed runtime/acquisition/evidence identities. Do not replace native source, binary, architecture, or codegen records.
3. **`/opt/colmap-dev/colmap.sha256`:** unchanged; continues to refer to the actual installed native binary.
4. **`/opt/colmap-python/environment-lock.json`:** retain the authoritative original bytes and hash. Its `image_digest` identifies the **native parent**, not the new derived image. Consumers must not silently rewrite this lock or mistake that field for the derived registry identity.
5. **`/opt/colmap-python/runtime-manifest.json`:** record actual interpreter/prefix/aliases, complete distribution versions and artifact hashes, bundled bootstrap identity, native preservation results, Python loaded-library evidence, invocation/environment, and explicit verification scope.

The new derived image's registry digest is supplied externally in the publication receipt/job contract; it cannot be embedded self-referentially in its own contents. The old image remains immutable and usable by its old digest. Use a new experimental publication identity, never retag or replace the existing candidate.

Preserve the conservative fields `mvs_codegen_policy=upstream_blackwell_ptx_workaround`, `gpu_execution_validated=false`, `byte_exactness_inherited=false`, and `required_gpu_validation=fresh_reference_map_gate`. CPU import/preparation success does not complete the GPU, MPS, or 632-map gates.

### Repository consumers and separate coordinator handoff

- Add an allowlisted image-layer recipe and locked-artifact installer/verifier under `dev/python`; do not change production `image/Dockerfile` or its independently governed runtime.
- Extend or add image-contract validation alongside `scripts/check_dev_contract.py`: understand schema 1 parent versus schema 2 derived image explicitly; validate unchanged native identities separately from added Python fields. The current checker expects schema 1 strictly and must not be bypassed with a permissive field dump.
- Any future Python-layer workflow needs separate build/validation/publication gates. Do not inherit build authority from the one-time inspection's `inspect_only` path, and do not accidentally export a registry build cache when publication is prohibited.
- Update `docs/pr8-dev-image.md` and contract documentation only when the implementation/evidence is approved and available.
- Photogram must separately prepare/review a new immutable job variant selecting the explicit shared interpreter and validating the new image/runtime identities. The current r4 `run.sh` still selects `JOB/../installed/python` and injects wheel CUDA directories into its library environment; image baking alone does not repair that integration. No such coordinator edit is part of this image-side work.

## 7. Required verification before declaring the runtime ready

The future authorized verification must retain bounded, non-secret artifacts covering:

1. **Acquisition:** exact lock hash, all 17 input hashes/lengths/public origins, interpreter ELF hash, compatible wheel metadata/tags, and retained license notices.
2. **Single-installation interface:** realpath checks for `/usr/local/bin/python` and `python3` to the one `/opt/colmap-python/bin/python3.14`; actual `sys.executable`, `sys.prefix`, version, ABI and site-packages; no added `/usr/bin` interpreter or benchmark-private runtime.
3. **Offline closure:** bundled bootstrap version, no-index/no-deps/hash-checked installation under disabled networking, `pip check`, and exact complete distribution manifest. No uncontrolled extras/resolution.
4. **CPU imports and preparation:** container imports/versions for PyCOLMAP, NumPy, SciPy, Matplotlib, Pillow and remaining importable locked modules; a small deterministic synthetic workload-preparation smoke (numeric operations, rendering/serialization, PyCOLMAP model preparation) with no source photos or GPU calls. This does not claim the full158 science workload or launcher integration passed.
5. **Read-only/no-network use:** invoke the shared interpreter through its explicit path and aliases in a container with no networking and a read-only root, allowing only a bounded disposable job scratch/cache directory. Check imports/preparation do not need a package index, external data, mutable installation, or writes into the shared prefix.
6. **Native preservation:** actual before/after native SHA256, source/toolchain/dependency identities, package inventory, exact unchanged global PATH/LD_LIBRARY_PATH, and resolved native library paths/hashes. Retain the native checksum entrypoint and runtime tile/PRNG settings.
7. **Process-local Python libraries:** loaded cudart/curand paths/hashes correspond to the locked wheel files and are separate from the unchanged native loader baseline. Do not infer this from import success alone.
8. **Contracts:** validate schema 2 and both manifest identities against observed files, preserving the original lock's parent binding and all schema 1 native values.
9. **Security and publishing safeguards:** fresh SBOM, secret/data/context checks, redistribution review and existing fail-closed vulnerability gate. The approved header-only exception remains package/version/base scoped and expires 2026-10-15; new Python/user-space findings receive no automatic exemption. If historical pins fail the gate, report the conflict rather than upgrade or waive them.
10. **Publication, only if separately authorized:** push precisely the verified image, record a new immutable digest, verify registry manifest/config identity and intended public pull access, and provide the derived contract plus full evidence to the coordinator. No mutable replacement.

GPU execution, MPS behavior, driver-JIT correctness, performance, and the fresh 632-map comparison remain **pending** and outside this CPU/image verification. No GPU rental is part of this design.

## 8. Review and authority boundary

This document resolves the arrangement: one shared neutral-prefix Python with aliases, locked historical dependencies, and unchanged native libraries. It supersedes the earlier benchmark-private prefix proposal.

The next step is owner review of this written design and explicit design/implementation handoff approval. Local implementation, acquisition/installation, CI, Git push/PR, image builds, registry publication/cache export, coordinator changes, and rentals are not resumed by writing or reviewing this document. Any later grant must name its permitted operations; the previous one-time inspection run does not authorize another run.
