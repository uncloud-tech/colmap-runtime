# Shared COLMAP Python Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one shared, exactly pinned Python/PyCOLMAP installation to the immutable PR8 dev image while preserving native COLMAP and its library environment.

**Architecture:** Layer on the published native digest, never rebuild COLMAP. Public artifacts are acquired in an explicitly authorized host phase; installation is offline inside the shared prefix. A schema-2 contract and strict native/Python evidence checks distinguish the new runtime from the unchanged parent.

**Tech Stack:** CPython 3.14.7, standard-library acquisition/metadata helpers, bundled pip 26.2.1, the 16 locked wheels, Docker BuildKit, GitHub Actions, unittest, Ruff, ShellCheck, Hadolint.

**Spec:** `docs/superpowers/specs/2026-10-05-shared-colmap-python-design.md`, owner-approved SHA256 `c0b53d3825201cd3e3e478142ca537150b32f95300ebfe294514fa150fad382b`.

## Global Constraints

- **Current authority: plan preparation only.** No task or command below is executed by writing this plan. Owner must review it and select execution method before implementation.
- Native parent: `ghcr.io/uncloud-tech/colmap-runtime-dev@sha256:8993096b761a11d210afc5c49cbc8b8622d0b96d36fb539b348089c18d97ac0b`, `linux/amd64`.
- Native source: `340f78310590cefda7cd3bb61ff0775ae5e2b59f`; binary `/opt/colmap-pr8/bin/colmap`, SHA256 `fc896cb9b6a5883285673a6cd1c21d768c5a2d554d7c52748a6ae63aeb59e34c`.
- One shared prefix `/opt/colmap-python`; executable `/opt/colmap-python/bin/python3.14`; `/usr/local/bin/python` and `python3` symlink to that executable. No `/usr/bin` replacement, private benchmark interpreter, or baked venv.
- CPython `3.14.7+20260924`; archive SHA256 `bd0d0568ccded07bbf1c87727230dc5dd0187e706a87da23c4de78388a229b78`; executable SHA256 `5a91882290532b2719eaca77c0f3a7448bd73b9214e56df57bc59004560a80c6`.
- Exact lock bytes: `dev/python/environment-lock.json`, SHA256 `a22ac04ee8febc9f46f281d7b01d200e73e75f2d380bbc02b0bffc4992ee45cd`; 17 artifacts, 258,592,337 bytes. Its `image_digest` and the derived contract's `native_parent_digest` are the parent's `sha256:8993096b761a11d210afc5c49cbc8b8622d0b96d36fb539b348089c18d97ac0b` (digest only, not the full registry reference).
- Exactly the spec's 16 historical wheel versions/bytes plus bundled bootstrap pip 26.2.1; no resolution, upgrade, source build, new artifact, or silent OS-package addition.
- Preserve global PATH and `LD_LIBRARY_PATH=/opt/deps/lib:/opt/colmap-pr8/lib`; no Python CUDA directory injection, loader-cache change, native source/toolchain replacement, or native recompilation.
- Runtime tile specialization, compact PRNG default 0, native checksum entrypoint and conservative GPU/codegen metadata stay unchanged. GPU/MPS/632-map validation remains pending.
- No benchmark photos, credentials, job tree, or unrelated files in the image/build context. Preserve notices; no new vulnerability exception or expiry extension (header-only exception ends 2026-10-15).
- The one inspection run's authority is exhausted. Acquisition, installation, builds, CI, Git push, PR, registry/cache publication and coordinator work each need separately scoped authority. No GPU rental in this plan.

## Review Focus

1. Unsafe lock destinations, redirects, symlinks or tar members: reject before exposing credentials, writing outside the intended directory, or installing anything (Tasks 1–2).
2. Wrong interpreter/alias/prefix or an extra/mismatched package: fail closed rather than accept a superficially successful import (Tasks 2–3).
3. Python imports accidentally using native CUDA, or native subprocesses inheriting Python CUDA paths: distinguish observed paths/hashes and preserve the native loader baseline (Task 3).
4. Legacy/schema-2 confusion, boolean-as-integer schema values, altered lock parent binding, or extra JSON fields: reject rather than bypass strict identity checks (Task 3).
5. Validation-only execution accidentally building native COLMAP or exporting/publishing a cache/image, including on failure: enforce explicit mode and default no publication (Task 4).

---

## Authority and execution stages

| Stage | Permitted only after explicit owner grant | Exclusions |
| --- | --- | --- |
| A: local implementation | Tasks 1–4 code, synthetic fixture tests, local lint/review and scoped local commits | No real artifact downloads/extraction/install, Docker execution, push, PR or CI |
| B: public acquisition | Download exact locked artifacts to an untracked confined directory | No new dependencies, credential forwarding or image operations |
| C: offline install/build/validation | Exact-parent Docker pull, Python-layer build and stated container checks on an approved runtime | No native rebuild, apt changes, rental, registry/cache export |
| D: Git/CI collaboration | Named feature-branch push; PR only if expressly authorized; named validation CI dispatch/run count | No main bypass, unapproved PR, retry, or reuse of old inspection authority |
| E: publication | One approved verified experimental image and evidence receipt | No mutable replacement, unapproved cache export or security waiver |

A combined grant may cover several rows, but the implementer must record which operations it covers before crossing each boundary. A flag in code does not itself confer owner authority. If CI is used for Stage C, Stage D must also be authorized. On denial/failure, stop and report; do not rerun or change the environment silently.

## File map and local test strategy

- `dev/python/locked_env.py`: pure lock, artifact, archive and wheel validation; requirements generation. No acquisition/installation on import.
- `dev/python/acquire.py`: official-public-only acquisition CLI, separate from the pure validator.
- `dev/python/install.py`: shared-prefix, offline-only installer CLI; verifies interpreter and exact installed closure.
- `dev/python/verify_runtime.py`: collect interpreter/alias/distribution, CPU smoke, native and process-local library evidence.
- `dev/python/Dockerfile` and `.dockerignore`: exact-parent, allowlisted Python-only layer and two aliases (Task 3, after installer/verifier interfaces exist).
- `scripts/check_dev_contract.py`: factor its existing strict native checker into a reusable function without relaxing schema-1 behavior.
- `scripts/check_dev_python_contract.py`: strict schema-2/runtime evidence validation and contract emission.
- `scripts/collect_dev_python_native.sh`: bounded before/after native snapshot (no network or mutation).
- `scripts/dev_python_commands.py`: context inventory/staging and command construction for the Python-layer workflow; validation mode cannot produce publication/cache-export commands. `.gitignore` excludes `dev/python/.staged/`.
- `.github/workflows/build-dev.yml`: separately selected Python-layer job in the existing registered workflow; native job skipped in Python mode. `.github/workflows/ci.yml` extends the existing Hadolint check to the new recipe without changing required-check names.
- `tests/test_dev_python_lock.py`, `test_dev_python_install.py`, `test_dev_python_runtime.py`, `test_dev_python_contract.py`, `test_dev_python_commands.py`: pure/generated-fixture tests runnable under the existing host Python, without the locked interpreter or real downloads/builds. `tests/dev_python_fixtures.py` supplies the shared literal schema fixtures.
- `docs/pr8-dev-image.md`: approved interface/evidence limits, updated with actual receipt only when available.

Run tests using unittest as in this repository. Do not install test dependencies. Network/process boundaries may use narrow traps or test doubles, but assertions concern the validator, emitted command or observed rejection—not the existence of a mock. Actual imports and container invariants are deferred to authorized Stage C.

Local verification commands (after Stage A approval; missing tools are a blocker, not permission to install):

```bash
python3 -m unittest discover -s tests -v
/home/Nethanja/.cache/colmap-pr8-tools/venv/bin/ruff format --check .
/home/Nethanja/.cache/colmap-pr8-tools/venv/bin/ruff check .
git ls-files -z '*.sh' | xargs -0 -r shellcheck
shellcheck scripts/collect_dev_python_native.sh
/home/Nethanja/.cache/colmap-pr8-tools/hadolint --config .hadolint.yaml image/Dockerfile dev/Dockerfile dev/python/Dockerfile
git diff --check
```

Expected: every command exits zero; unittest reports no failures/errors. Run scoped checks before commits, then the full set after Task 4. These are future execution instructions, not verification already performed.

## Task 1: Validate the exact public environment inputs

**Files:** create `dev/python/locked_env.py`, `dev/python/acquire.py`, `tests/test_dev_python_lock.py`; retain and, when local implementation is authorized, track the existing exact `dev/python/environment-lock.json`.

**Interfaces:**
- `load_lock(path: Path) -> dict`: hash-check the complete authoritative lock before parsing; validate schema, parent, single interpreter artifact, count and totals.
- `verify_file(path: Path, artifact: dict) -> None`: reject symlink/nonregular file, length/hash mismatch, and changed identity during reading.
- `validate_wheel(path: Path, artifact: dict) -> dict`: return name/version/tags/license-member inventory after validating dist-info metadata, locked destination and compatible cp314/py3 Linux x86_64 tags.
- `validate_tar_members(members: list[tarfile.TarInfo]) -> None`: pure validation of layout/links and the lock's 150000000-byte maximum, tested independently of archive hashes.
- `validate_archive(path: Path) -> None`: verify the official archive hash, call member validation, and verify its interpreter bytes without installing/extracting to a runtime.
- `requirements_text(lock: dict) -> str`: exact `name==version --hash=sha256:...` entries, no extras or source requirements.
- Acquisition CLI: `python3 -m dev.python.acquire --lock dev/python/environment-lock.json --output DIRECTORY`; real invocation requires Stage B.

- [ ] **Write RED tests:** `test_exact_lock_identity_and_totals` asserts the global lock hash, parent, 1 interpreter + 16 wheels and 258592337 total bytes; `test_altered_lock_rejected` changes a copy and expects `ValueError`; `test_file_sha_size_and_symlink_rejected` uses synthetic bytes/paths; `test_unsafe_destination_uri_and_archive_link_rejected` covers traversal, nonpublic origins, embedded URL userinfo and escaping tar links; `test_wheel_metadata_or_tag_mismatch_rejected` generates minimal ZIP fixtures with deliberately wrong identity/tags; `test_requirements_are_only_exact_hashed_wheels` asserts 16 literal locked pins and no extras.

Representative unittest assertion (the other named cases use the mutations specified above):

```python
def test_exact_lock_identity_and_totals(self):
    lock = load_lock(Path("dev/python/environment-lock.json"))
    self.assertEqual(len(lock["artifacts"]), 1)
    self.assertEqual(len(lock["dependency_artifacts"]), 16)
    self.assertEqual(
        sum(a["size_bytes"] for a in lock["artifacts"] + lock["dependency_artifacts"]),
        258592337,
    )
    self.assertEqual(lock["interpreter"]["version"], "3.14.7")
    self.assertEqual(
        lock["image_digest"],
        "sha256:8993096b761a11d210afc5c49cbc8b8622d0b96d36fb539b348089c18d97ac0b",
    )
```

- [ ] **Observe RED:** `python3 -m unittest discover -s tests -p test_dev_python_lock.py -v`; feature tests fail because the validator is missing, not because fixture preparation contacts the network.
- [ ] **Implement minimal validator/acquirer:** standard library only; streaming size/hash checks; safe bounded archive validation; only official lock origins and their official release-asset redirects. Do not log signed redirect URLs, credential values or environment dumps. Temporary downloads are confined, atomically adopted only after verification, and never followed through a symlink. Generate requirements from validated lock data.
- [ ] **Observe GREEN:** run the targeted command and full suite; acquisition is tested with fixtures/controlled boundaries, not the 17 real artifacts. Actual downloads remain gated.
- [ ] **Review and local commit:** only Task 1 files; `dev: validate exact shared Python lock and public artifacts`.

## Task 2: Offline single-prefix installer

**Files:** create `dev/python/install.py`, `tests/test_dev_python_install.py`.

**Interfaces:** consume Task 1 helpers.
- `installation_commands(prefix: Path, artifacts: Path, requirements: Path) -> list[list[str]]`: produce bundled ensurepip, isolated offline/hash-checked wheel install, and pip check commands.
- `validate_installation_context(prefix: Path, executable: Path, version: str, executable_sha256: str) -> None`: require the approved prefix/interpreter identity; never install into system/project Python or a symlinked prefix.
- `validate_distributions(installed: dict[str, str], lock: dict) -> None`: exactly locked16 plus pip26.2.1; reject extras/missing/mismatched distributions.
- `alias_targets(prefix: Path) -> dict[Path, Path]`: the two approved `/usr/local/bin` names target the same explicit interpreter; pure planning, not filesystem mutation.
- Installer CLI under the actual approved interpreter, not system Python; direct module execution must not install at import time.

- [ ] **Write RED tests:** `test_wrong_prefix_interpreter_and_version_refused`; `test_installer_commands_have_no_index_resolution_or_upgrade`; `test_missing_extra_and_wrong_bootstrap_distribution_refused`; `test_alias_plan_resolves_both_names_to_one_executable`. Requirements use synthetic files and exact literals `/opt/colmap-python/bin/python3.14`, `--no-index`, `--no-deps`, `--require-hashes`, `--only-binary=:all:` and pip26.2.1. Do not perform installation in these tests.

```python
def test_alias_plan_resolves_both_names_to_one_executable(self):
    self.assertEqual(
        alias_targets(Path("/opt/colmap-python")),
        {
            Path("/usr/local/bin/python"): Path("/opt/colmap-python/bin/python3.14"),
            Path("/usr/local/bin/python3"): Path("/opt/colmap-python/bin/python3.14"),
        },
    )
```

- [ ] **Observe RED:** `python3 -m unittest discover -s tests -p test_dev_python_install.py -v`.
- [ ] **Implement the offline installer:** run only under the verified relocated interpreter; bootstrap bundled ensurepip, install exact hashed requirements without dependencies/index/network, and verify installed closure. Retain pip/ensurepip/notices; return the pure alias plan but leave link creation to Task 3's recipe. No import-time mutation or system/project Python fallback.
- [ ] **Observe GREEN locally:** targeted tests, full suite and existing pinned linters. Actual alias/interpreter/install assertions require Stage C.
- [ ] **Review and local commit:** Task 2 files only; `dev: define offline shared Python image layer`.

## Task 3: Strict contracts and native/Python runtime verification

**Files:** create `dev/python/verify_runtime.py`, `dev/python/Dockerfile`, `dev/python/.dockerignore`, `scripts/check_dev_python_contract.py`, `scripts/collect_dev_python_native.sh`, `tests/dev_python_fixtures.py`, `tests/test_dev_python_runtime.py`, `tests/test_dev_python_contract.py`; modify `scripts/check_dev_contract.py` while preserving its existing tests.

**Interfaces:**
- Existing native module: extract `expected_native_contract(binary_sha: str) -> dict` and `verify_native(directory: Path, contract: dict) -> None`; keep `verify(directory)` loading and strictly validating schema 1 as before.
- Native snapshot parser: `read_native_snapshot(directory: Path) -> dict` validates the named snapshot files and canonicalizes the observed identity records.
- Python collector: `collect_runtime(prefix: Path, lock: dict, scratch: Path, native_before: dict, native_after: dict) -> dict`; record actual interpreter/realpaths/ABI, full versions, loaded CUDA file identities, invocation/env, CPU smoke and scope. It is not invoked under host Python by local tests.
- Pure runtime validation: `validate_runtime(evidence: dict, lock: dict) -> None`.
- Installed identity check: `verify_installed_files(prefix: Path, expected: dict) -> None`; validate recorded relative file hashes/sizes and internal symlink targets, reject changed/missing/unexpected entries. Exclude only the runtime manifest itself (its hash is bound by the outside image contract); scratch lives outside the prefix.
- Pure derived contract: `make_contract(native: dict, runtime: dict, runtime_manifest_sha256: str) -> dict`; `verify_python(directory: Path) -> None` validates observed evidence, schema 2 and exact allowed fields.
- Test helper `valid_runtime_fixture() -> dict` in `tests/dev_python_fixtures.py` supplies the complete literal manifest shape below with the global interpreter/lock/pin identities and deterministic native/library/file records, without real imports or installation.
- Snapshot shell script outputs `binary-sha256.txt`, `native-library-files.sha256`, `native-library-resolution.txt`, `native-tools.sha256`, `native-source-identity.txt`, `system-packages.txt`, and `native-env.txt` into a caller-specified empty evidence directory. Also copy the contract/BUILD-MANIFEST and record `patch-match-help.txt`/`runtime-defaults.txt` in the existing native checker's exact format. Canonicalize library paths; do not compare ASLR addresses.

Schema 2 retains exactly the schema-1 native fields apart from the discriminator. Add only `native_parent_digest`, `environment_lock_sha256` and `python`. The `python` object has `prefix`, `executable`, `aliases`, `version`, `release`, `archive_sha256`, `executable_sha256`, `bootstrap`, `runtime_manifest_path`, `runtime_manifest_sha256`, and `global_library_environment`. Detailed package/artifact/native/library/import evidence lives in `runtime-manifest.json` and is hash-bound by the contract; never put its own hash inside itself.

Runtime manifest schema 1 has these top-level fields: `schema_version`, `interpreter`, `aliases`, `distributions`, `installed_files`, `artifacts`, `bootstrap`, `invocation`, `native_before`, `native_after`, `python_libraries`, `cpu_smoke`, and `verification_scope`. `interpreter` records `path`, `realpath`, `prefix`, `base_prefix`, `version`, `release`, `sha256`, and `soabi`; `aliases` maps both alias paths to the real interpreter. `distributions` is a canonical-name/version mapping; `installed_files` records prefix-relative regular-file size/SHA256 or symlink target after installation and smoke collection, excluding the manifest itself. `artifacts` contains the original validated public artifact records. `bootstrap` records pip version and the bundled ensurepip wheel hash observed within the pinned archive. `invocation` contains the argv and relevant non-secret environment only. Native snapshots contain binary/source/tool hashes, package inventory, global environment and canonical library-path/hash mappings. `python_libraries` contains cudart/curand records with `path`, `realpath`, and `sha256`. `cpu_smoke` contains module import versions and individual named preparation-check results. `verification_scope` records network-disabled/read-only conditions and `gpu_validated=false`, `mps_validated=false`, `reference_map_gate_passed=false`.

- [ ] **Write RED tests:** `test_legacy_contract_stays_strict`; `test_schema2_checks_native_projection_without_relaxation`; `test_boolean_schema_extra_fields_and_wrong_parent_rejected`; `test_changed_binary_library_or_global_env_rejected`; `test_python_cuda_outside_locked_wheel_prefix_rejected`; `test_false_gpu_or_inherited_exactness_claim_rejected`; `test_wrong_alias_prefix_package_or_manifest_hash_rejected`; `test_modified_or_unexpected_installed_file_rejected`. Use hand-authored evidence fixtures with literal expected paths/hashes and deliberate individual mutations.

```python
def test_boolean_runtime_schema_rejected(self):
    evidence = valid_runtime_fixture()
    evidence["schema_version"] = True
    with self.assertRaises(ValueError):
        validate_runtime(evidence, load_lock(Path("dev/python/environment-lock.json")))
```

- [ ] **Observe RED:** run `python3 -m unittest discover -s tests -p 'test_dev_python_runtime.py' -v` and the same command with `test_dev_python_contract.py`; existing `test_dev_contract.py` must stay GREEN during refactoring.
- [ ] **Implement minimal evidence/contract checks:** strict schema type and key-set checks; validate the schema-1 projection with the reusable native checker; compare exact before/after native identities. Append Python-prefixed BUILD-MANIFEST entries without changing native values; leave `colmap.sha256` and entrypoint untouched. Preserve original lock bytes and its parent digest.
- [ ] **Implement the exact-parent image recipe:** builder and final stages both use the global digest. Verify archive SHA before native tar extraction into the shared prefix; the host has already validated tar members. Installer runs under `RUN --network=none`. Copy only the finished prefix and explicit contract/evidence updates to the final parent, then create the two aliases without replacing another interpreter. Preserve final WORKDIR/entrypoint/environment; no apt/native build/loader operations. Transport wheels/archive remain in the builder only. Dockerfile lint is local checking, not build authority.
- [ ] **Make helpers importable:** image entries are `libexec/install.py` and `libexec/verify-runtime.py` under the prefix, using `-E -s -B` and importing the copied `libexec/dev/python/locked_env.py`. Both contract checkers live in `libexec/scripts/`; invoke `-m scripts.check_dev_python_contract` from that trusted libexec directory and import `scripts.check_dev_contract`. No ambient PYTHONPATH/global `.pth` workaround.
- [ ] **Bind build and external evidence without false scope claims:** snapshot the builder's untouched parent before runtime installation. In the final stage, after prefix copying and alias creation, collect native-after/runtime evidence, inventory the finished prefix (excluding only the manifest), emit the manifest containing that inventory, then emit schema 2 with its hash. Build-time evidence records read-only status truthfully; separate final-container evidence demonstrates read-only operation and is compared against baked identities. Do not rewrite image contents after validation or claim build-time root was read-only.
- [ ] **Implement CPU smoke collection:** deterministic NumPy/SciPy calculations, in-memory Matplotlib/Pillow rendering/serialization, and synthetic PyCOLMAP camera/reconstruction preparation. Import remaining importable locked modules and record distribution versions. No benchmark photos/job tree/GPU calls. Record loaded cudart/curand canonical paths and hashes from the Python process, not just import success. Unexpected OS/loader requirements stop the phase.
- [ ] **Observe GREEN locally:** pure fixture tests plus all existing tests; do not import real locked PyCOLMAP or create a runtime merely to satisfy local tests. Stage C supplies actual interpreter/container evidence.
- [ ] **Review and local commit:** `dev: verify shared runtime and preserve native image contracts`.

## Task 4: Explicit validation/publication boundaries and documentation

**Files:** create `scripts/dev_python_commands.py`, `tests/test_dev_python_commands.py`; modify `.github/workflows/build-dev.yml`, `.github/workflows/ci.yml`, `.gitignore`, `docs/pr8-dev-image.md`.

**Interfaces:**
- `allowed_context_paths(lock: dict) -> frozenset[Path]` and `validate_context_inventory(relative_paths: set[Path], allowed: frozenset[Path]) -> None`: exact recipe/runtime/lock inputs, locked artifact filenames and explicitly staged helpers only; reject unexpected files/symlinks.
- `stage_context(repo: Path, artifacts: Path) -> Path`: reverify real artifact bytes, stage approved helper copies and artifacts under `dev/python/.staged/`, return `repo / "dev/python"`. Actual staging of real artifacts requires Stage B; local tests exercise pure inventory and generated fixtures only.
- `validation_commands(context: Path, image_tag: str, reports: Path) -> list[list[str]]`: require the repository's exact `dev/python` context; emit only explicit parent pull/Python build/load and no-network/read-only observations, never native build, push or registry cache export.
- `publication_commands(image_tag: str, repository: str, verified_image_id: str, verification_passed: bool) -> list[list[str]]`: reject false verification or missing/non-digest image ID; prepared only in the independently approved publication phase. Actual image ID comparison remains required before tagging/push; this function does not grant owner authority.
- Local candidate tag is `colmap-dev:pr8-python`; a future publication uses `ghcr.io/uncloud-tech/colmap-runtime-dev:pr8-python-<workflow-sha>-<run-id>-<attempt>`, never the old native tag/digest.
- Workflow dispatch input `runtime_layer` is a typed choice (`native`, `python`), default `native`; Python mode skips the native build job. Existing `publish` remains boolean/default false and does not grant authority.

- [ ] **Write RED tests:** `test_validation_command_set_has_no_push_or_cache_export_or_native_build`; `test_non_python_context_is_refused`; `test_validation_failures_never_construct_publication_commands`; `test_publication_requires_verified_image_identity`; `test_wrong_parent_platform_and_mutable_reference_rejected`; `test_extra_secret_or_symlink_context_member_rejected`. Assert pure command/decision outputs, not source text or a mock Docker invocation. No Docker/registry operations are executed locally.

```python
def test_validation_failures_never_construct_publication_commands(self):
    with self.assertRaises(ValueError):
        publication_commands(
            "colmap-dev:pr8-python",
            "ghcr.io/uncloud-tech/colmap-runtime-dev",
            "sha256:" + "a" * 64,
            False,
        )
```

- [ ] **Observe RED:** `python3 -m unittest discover -s tests -p test_dev_python_commands.py -v`.
- [ ] **Implement mode-specific workflow:** reuse the registered workflow path so registration does not require an unapproved default-branch update. Separate public acquisition, Python-layer build, native/runtime observations, contract/CPU checks, SBOM/security/data/license gates and optional publication. No registry cache export in Python validation mode, no install/build triggered merely by push, no automatic retries. Define `python_validate` for Python mode with `publish=false` (`contents:read` only) and `python_validate_publish` for Python mode with `publish=true` (`contents:read`, `packages:write`), both using the same checked scripts. The latter requires a combined acquisition/build/CI/publication grant and verifies its newly loaded image before pushing; never assume it is identical to a prior validation-only image. Publication-only authority is not permission to invoke that build-and-publish job or rebuild a lost candidate. A publication-only operation must use a still-available verified image or stop and request the missing build/CI authority.
- [ ] **Implement allowlisted context handling:** `.staged/artifacts/` holds the interpreter archive and 16 wheel basenames; `.staged/helpers/scripts/` holds both contract checkers; `.staged/helpers/collect_dev_python_native.sh` is the native collector. Task 3's COPY rules use these exact locations. Track no staged artifacts/helpers: add `.gitignore` protection. `.dockerignore` denies everything except explicit recipe/runtime/lock and those exact staged filenames; reject unexpected members before Docker reads the context. Exclude `.pi`, credentials, job trees, photos, reports and unrelated files. Add artifact SHA256SUMS and exact recipe/ref/image IDs. Failure paths retain bounded non-secret evidence without publishing.
- [ ] **Extend existing Hadolint coverage:** add `dev/python/Dockerfile` to `.github/workflows/ci.yml`'s checked paths; preserve the `tests`, `python-lint`, `shellcheck`, `hadolint` check identities and branch protection. This does not authorize triggering them.
- [ ] **Document shared aliases, explicit benchmark invocation and separate coordinator handoff:** no claim that baking alone fixes r4's interpreter/library selection; GPU/MPS/632 gates remain pending. Do not invent a derived digest or change old tags.
- [ ] **Observe GREEN locally:** all new tests, full unittest suite, pinned Ruff format/check, ShellCheck, Hadolint and `git diff --check`. Review code/context/authority boundaries before any real acquisition/build.
- [ ] **Review and local commit:** `ci: gate shared Python validation and publication separately`.

## Separately gated operational verification—not implementation permission

Each item below requires the applicable owner grant from the authority table. It is deliberately not a default continuation of Task 4.

- [ ] **Stage B approval:** record permission for public acquisition; run the acquisition CLI once against the original lock, verify all 17 sizes/hashes/metadata/notices. Missing/unavailable bytes stop; do not substitute versions or mirrors with different bytes.
- [ ] **Stage C/D setup approval:** identify the approved container runtime/runner and any permitted feature push, PR, dispatch and run count. Any automatic checks caused by an approved push/PR must also be included in the CI grant. Check authorization before using the known host-restricted credential helper; never expose or persist credential values. Do not alter shared gh settings or main rules. If dispatch fails or a workflow needs broader authority, stop.
- [ ] **Parent baseline:** pull the exact linux/amd64 digest and collect native snapshot using only an approved observation container. Preserve parent/global config and native contract records; do not install in the baseline.
- [ ] **Offline Python build/install:** build only the new layer and load it locally; no `--cache-to`/registry publication. Interpreter ELF hash and offline pip closure must match the globals. Do not recompile native COLMAP.
- [ ] **Observed final-image invariants:** run explicit interpreter and both aliases in `--network none --read-only` containers with bounded scratch. Verify imports/preparation, one shared prefix, exact versions/bootstrap, package/file closure, actual process-local Python CUDA files, unchanged global/native environment and before/after library hashes. Launch native resolution checks from the Python process too, so the inherited environment is tested. Create one disposable scratch-owned venv using bundled ensurepip with networking off; verify its base prefix is the shared installation, its own prefix is scratch, and it leaves the shipped runtime unchanged. Produce contract/manifest evidence and verify all artifact checksums.
- [ ] **Security/license review:** generate fresh SBOM and secret/data/context results, retain license notices, run existing fail-closed security policy. New Python/user-space HIGH/CRITICAL findings, expired exceptions or missing libraries are blockers, not permission to upgrade or waive.
- [ ] **If CI authorized:** dispatch only the reviewed Python validation mode with `publish=false`, within approved run count; no registry cache exports, PR or retries unless separately granted. Confirm native job skipped from actual run evidence, not merely from YAML intent.
- [ ] **Stage E approval, separately:** bind approved image ID to successful evidence, publish a new unique experimental identity, verify manifest/config/digest and intended public access. Return actual digest, native before/after hash, interpreter identity, full dependency manifest, contract and checksummed evidence. Do not replace the existing native candidate.
- [ ] **Coordinator handoff only:** supply paths/identity/evidence; photogram owns separately approved immutable job selection/library integration. Report CPU scope and GPU/MPS/632 pending. No coordinator edits/rental execution here.

## Plan self-review (documentation only)

- [x] Spec coverage: shared interface/offline closure → Tasks 1–2; native isolation/contracts → Task 3; safeguards/consumer scope → Task 4 and gated operations; coordinator/GPU work explicitly excluded.
- [x] Step scan: named failing cases, representative assertions, exact interfaces and verification commands; no placeholder digest or implementation executed.
- [x] Type/interface consistency: artifact lock versus derived digest distinguished; helper copy/import paths and staged context mapped; native checker retains schema-1 behavior.
- [x] Review Focus: all five failure classes have named negative tests; actual container/network/library observations remain gated, not simulated as proof.
- [x] Proportion: four coupled deliverables, no general-purpose packaging framework or feature beyond the approved shared runtime; plan is comparable in scale to the spec.

## Execution handoff

This plan awaits owner review and execution-method selection. Recommend **Native** execution for the four tightly coupled local tasks: shared lock/contract boundaries benefit from one maintained context, and external stages remain independently gated. This is a recommendation, not authorization to start.

- **Native:** implement locally in this session using executing-plans, then an explicitly authorized independent whole-branch review before external stages.
- **Subagent-driven:** separate task implementers and reviewers using subagent-driven-development; owner selection must include delegation authority and the same external-operation boundaries.

Request the owner to confirm plan coverage, select a method and specify the initial authorized stage. No code, acquisition, installation, build, CI, push/PR, publication, coordinator or rental operation is authorized by this plan's creation.
