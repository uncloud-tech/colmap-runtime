#!/usr/bin/env bash
# External verification only. Mount read-only; do not modify the cached image.
set -euo pipefail
SRC=/opt/src/colmap-pr8
BUILD="$SRC/build"
OUT=/evidence
mkdir -p "$OUT"
test -f "$BUILD/CMakeCache.txt"
test -x /opt/colmap-pr8/bin/colmap
sha256sum -c /opt/colmap-dev/colmap.sha256
cp /opt/colmap-dev/image-contract.json "$OUT/image-contract.json"
colmap patch_match_stereo -h > "$OUT/patch-match-help.txt" 2>&1
printf 'COLMAP_PATCH_MATCH_COMPACT_PRNG=%s\ncolmap=%s\n' \
  "${COLMAP_PATCH_MATCH_COMPACT_PRNG:?}" "$(command -v colmap)" > "$OUT/runtime-defaults.txt"
cp /opt/colmap-dev/BUILD-MANIFEST.txt "$OUT/BUILD-MANIFEST.txt"
cp /opt/colmap-dev/EXPERIMENTAL-USE.txt "$OUT/EXPERIMENTAL-USE.txt"
cp -r /opt/colmap-dev/security-remediation "$OUT/security-remediation"
dpkg-query -L linux-libc-dev > "$OUT/header-package-files.txt"
test "$(dpkg-query -W -f='${Version}' linux-libc-dev)" = '6.8.0-55.57'
test ! -e /opt/nvidia/nsight-compute/2025.1.1/host/target-linux-x64/plugins/efa_metrics/nic_sampler
cp "$BUILD/CMakeCache.txt" "$OUT/CMakeCache.txt"
# Preserve original manifest verbatim; directory-scoped CUDA flags are not
# reliably represented by its fast_math field. Ninja commands are recipes,
# not a claim that verbose NVCC execution was captured on this cached run.
ninja -C "$BUILD" -t commands > "$OUT/ninja-command-recipes.txt"
grep 'nvcc.*patch_match_cuda.cu' "$OUT/ninja-command-recipes.txt" > "$OUT/mvs-nvcc-command-recipe.txt"
grep -q -- '--use_fast_math' "$OUT/mvs-nvcc-command-recipe.txt"
grep -q -- '--default-stream per-thread' "$OUT/mvs-nvcc-command-recipe.txt"
nvcc --version > "$OUT/nvcc.txt"
g++ --version > "$OUT/compiler.txt"
dpkg-query -W -f='${Package}\t${Version}\n' > "$OUT/system-packages.txt"
find /opt/deps -type f | sort > "$OUT/installed-dependency-files.txt"
sha256sum /opt/colmap-pr8/bin/colmap > "$OUT/binary-sha256.txt"
ldd /opt/colmap-pr8/bin/colmap > "$OUT/installed-library-resolution.txt"
if grep -q 'not found' "$OUT/installed-library-resolution.txt"; then
  echo 'FAIL: installed binary has unresolved runtime libraries' >&2; exit 1
fi
grep -q '^source_commit=340f78310590cefda7cd3bb61ff0775ae5e2b59f$' "$OUT/BUILD-MANIFEST.txt"
grep -q '^cuda_architectures=89-real;120-real$' "$OUT/BUILD-MANIFEST.txt"
{
  echo 'Original image BUILD-MANIFEST.txt is retained without correction.'
  echo 'fast_math and other directory-scoped flags: use mvs-nvcc-command-recipe.txt, not manifest inference.'
  echo "Boost recipe retains the nonfatal unknown selector next_prior; iterator owns boost/next_prior.hpp."
  echo "Original build warning: Library 'next_prior' given in BOOST_INCLUDE_LIBRARIES has not been found."
  echo 'Header ownership does not establish availability: hashes below verify actual installed files.'
} > "$OUT/manifest-corrections.txt"
# Verify all directly included Boost headers, including bundled source and
# Windows-only asio (available in this image, not a Linux build requirement).
grep -rhoE '^#include <boost/[^>]+>' "$SRC/src" | sort -u > "$OUT/boost-includes.txt"
while IFS= read -r line; do
  header="${line#*<}"; header="${header%>}"
  test -r "/opt/deps/include/$header"
  sha256sum "/opt/deps/include/$header"
done < "$OUT/boost-includes.txt" > "$OUT/installed-boost-headers.txt"
test -s "$OUT/installed-boost-headers.txt"
# Archives and baked helpers: identity/inventory only, NOT nonroot-control usability.
sha256sum /opt/archives/* /opt/colmap-dev/*.sh /opt/colmap-dev/patches/* > "$OUT/helper-archive-sha256.txt"
printf '%s  %s\n' 9f132c88a3b2b8b6b8680c5eff4a20dc1dbd96fe2da1f47f4356c5d5aedb8575 \
  /opt/archives/colmap-parent-78f41b8c6cb2629775115ee2dc3b50f21a51c4f1.tar.gz | sha256sum -c -
{
  echo 'Baked verify-targets.sh is superseded by the mounted external verification for this run.'
  echo 'Baked helper defaults point to the PR8 source/build tree.'
  echo 'UID1002 control/helper execution and standalone sanitizer execution are NOT validated here.'
} > "$OUT/helper-limitations.txt"
{
  echo 'Base: nvidia/cuda:12.8.1-devel-ubuntu24.04@sha256:4b9ed5fa8361736996499f64ecebf25d4ec37ff56e4d11323ccde10aa36e0c43'
  echo 'Installed toolkit version: see nvcc.txt (authoritative; version.json may be absent).'
  echo 'CUDA 12.8 Linux toolkit minimum driver: 570.26; target driver: 570.195.03.'
  echo 'Static compatibility only. compute_90 PTX requires driver JIT on Blackwell; no GPU/JIT validation performed.'
  echo 'The CUDA 12.x minor compatibility floor alone does NOT prove PTX JIT support.'
} > "$OUT/cuda-compat.txt"
if test -f /usr/local/cuda/version.json; then
  cp /usr/local/cuda/version.json "$OUT/cuda-version.json"
else
  echo '/usr/local/cuda/version.json absent; nvcc.txt records actual toolkit.' > "$OUT/cuda-version-note.txt"
fi
# CPU-only scope: exactly the sweep_tile host test. Full CTest/device suite skipped.
ctest --test-dir "$BUILD" -N -R sweep_tile | tee "$OUT/ctest-list.log"
grep -Eq 'Total Tests: [1-9][0-9]*' "$OUT/ctest-list.log"
printf '%s\n' 'Selected: sweep_tile host test only; all other CTest tests (including device-required tests) intentionally excluded.' > "$OUT/cpu-test-scope.txt"
ctest --test-dir "$BUILD" --no-tests=error --output-on-failure --verbose -R sweep_tile | tee "$OUT/cpu-tests.log"
grep -Eq '100% tests passed, 0 tests failed out of [1-9][0-9]*' "$OUT/cpu-tests.log"
if grep -Eiq 'skipped|not run|disabled' "$OUT/cpu-tests.log"; then
  echo 'FAIL: selected CPU test did not execute' >&2; exit 1
fi
# Record all MVS CUDA objects separately, never aggregate evidence across objects.
# Only the production colmap_mvs_cuda target receives the workaround, NOT
# gpu_mat_test.cu.o (which legitimately retains the global sm120 target).
mapfile -t objects < <(find "$BUILD/src/colmap/mvs/CMakeFiles/colmap_mvs_cuda.dir" -type f -name '*.cu.o' | sort)
(( ${#objects[@]} > 0 ))
printf '[' > "$OUT/mvs-objects.json"
for i in "${!objects[@]}"; do
  f="${objects[$i]}"
  if (( i > 0 )); then printf ',' >> "$OUT/mvs-objects.json"; fi
  # Fixed build tree contains no JSON special characters in object paths.
  printf '"%s"' "$f" >> "$OUT/mvs-objects.json"
  sha256sum "$f" >> "$OUT/mvs-object-sha256.txt"
  cuobjdump --list-elf "$f" > "$OUT/mvs-$i.elf-list.txt"
  cuobjdump --list-ptx "$f" > "$OUT/mvs-$i.ptx-list.txt"
  cuobjdump --dump-sass --gpu-architecture sm_89 "$f" > "$OUT/mvs-$i.sass.txt"
  cuobjdump --dump-ptx "$f" > "$OUT/mvs-$i.ptx.txt"
done
printf ']\n' >> "$OUT/mvs-objects.json"
