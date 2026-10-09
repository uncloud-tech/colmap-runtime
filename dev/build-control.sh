#!/usr/bin/env bash
# Build ONE named control toolchain (stock or seed) OFFLINE from a LOCAL,
# hash-verified source archive into its own writable source/build/install roots.
#
# Both arms are built with IDENTICAL flags; the ONLY difference is the seed
# overlay patch.  The upstream MVS Blackwell PTX workaround is preserved: with
# the explicit architecture list below c6 emits native sm_86/sm_89 SASS plus
# compute_70/compute_90 PTX for MVS and drops sm_100+ from that target.  No
# sm_120 MVS source-toggle patch is applied.
#
# Usage: build-control.sh <name> <archive> <archive-sha256> [patch] [patch-sha256]
set -euo pipefail
NAME="${1:?usage: build-control.sh <name> <archive> <sha256> [patch] [patch-sha256]}"
ARCHIVE="${2:?}"; ARCHIVE_SHA="${3:?}"; PATCH="${4:-}"; PATCH_SHA="${5:-}"
[ -n "$PATCH_SHA" ] || true

ARCH="86-real;89-real;120-real;70-virtual"
DEP=/opt/deps
SRC="/opt/src/colmap-${NAME}"
BUILD="${SRC}/build"
PREFIX="/opt/colmap-${NAME}"
EVID="/opt/photogram-dev/evidence/${NAME}"
mkdir -p "$SRC" "$BUILD" "$PREFIX" "$EVID/mvs"

echo "${ARCHIVE_SHA}  ${ARCHIVE}" | sha256sum -c -
tar -xzf "$ARCHIVE" -C "$SRC" --strip-components=1

if [ -n "$PATCH" ]; then
  echo "${PATCH_SHA}  ${PATCH}" | sha256sum -c -
  ( cd "$SRC" && git init -q && git add -A \
      && git -c user.email=dev@local -c user.name=dev commit -qm "c6 base" \
      && git apply --check "$PATCH" && git apply "$PATCH" )
fi

# The source tree is private and writable: c6's GenerateVersionDefinitions.cmake
# writes the ignored src/colmap/util/version.cc INSIDE the source directory.
cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_PREFIX_PATH="$DEP" -DBOOST_ROOT="$DEP" \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
  "-DCMAKE_CUDA_ARCHITECTURES=${ARCH}" \
  -DCUDA_ENABLED=ON -DHIP_ENABLED=OFF -DMVS_ENABLED=ON \
  -DGUI_ENABLED=OFF -DOPENGL_ENABLED=OFF -DONNX_ENABLED=OFF \
  -DCGAL_ENABLED=OFF -DCASPAR_ENABLED=OFF -DLSD_ENABLED=OFF \
  -DTESTS_ENABLED=ON -DBUILD_SHARED_LIBS=OFF -DCCACHE_ENABLED=OFF \
  -DFETCH_BOOST=OFF -DFETCH_POSELIB=OFF -DFETCH_FAISS=OFF -DFETCH_ONNX=OFF \
  -DFETCHCONTENT_FULLY_DISCONNECTED=ON -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  2>&1 | tee "$EVID/configure.log"

# Derive the install-required static library targets from the recursive
# generated cmake_install.cmake inputs (validated in Task0: 25 libraries).
mapfile -t libs < <(find "$BUILD" -name cmake_install.cmake -print0 \
  | xargs -0 awk '/TYPE STATIC_LIBRARY FILES/ {n=split($0,a,"\""); p=a[n-1]; sub(/^.*\/lib/,"",p); sub(/\.a$/,"",p); print p}' \
  | sort -u)
printf '%s\n' "${libs[@]}" | sed '/^$/d' | sort -u > "$EVID/install-library-targets.txt"
mapfile -t libs < "$EVID/install-library-targets.txt"
if (( ${#libs[@]} != 25 )); then
  echo "STOP: expected 25 install-required static libraries; found ${#libs[@]}" >&2
  exit 93
fi

ninja -C "$BUILD" -t targets all > "$EVID/ninja-targets.txt"
for target in "${libs[@]}" colmap_main colmap_mvs_depth_map_test colmap_mvs_normal_map_test colmap_mvs_mat_test; do
  grep -q "^${target}: " "$EVID/ninja-targets.txt" || { echo "STOP: missing Ninja target ${target}" >&2; exit 93; }
done

cmake --build "$BUILD" --parallel "$(nproc)" --target \
  "${libs[@]}" colmap_main \
  colmap_mvs_depth_map_test colmap_mvs_normal_map_test colmap_mvs_mat_test \
  2>&1 | tee "$EVID/build.log"

# Selected MVS host tests must execute and pass.
ctest --test-dir "$BUILD" -N -R '^mvs/(depth_map_test|normal_map_test|mat_test)$' > "$EVID/selected-tests.txt"
grep -Eq '^Total Tests: 3$' "$EVID/selected-tests.txt"
ctest --test-dir "$BUILD" --no-tests=error --output-on-failure \
  -R '^mvs/(depth_map_test|normal_map_test|mat_test)$' 2>&1 | tee "$EVID/host-tests.log"
grep -Eq '100% tests passed, 0 tests failed out of 3' "$EVID/host-tests.log"
if grep -Eiq 'skipped|not run|disabled' "$EVID/host-tests.log"; then
  echo 'STOP: a selected MVS host test did not execute' >&2; exit 1
fi

cmake --install "$BUILD"
cp "$BUILD/install_manifest.txt" "$EVID/install_manifest.txt" 2>/dev/null || true

# Absolute-path help + binary identity + generated version.cc (recorded separately).
"$PREFIX/bin/colmap" -h > "$EVID/help.txt" 2>&1
sha256sum "$EVID/help.txt" > "$EVID/help.sha256"
sha256sum "$PREFIX/bin/colmap" > "$EVID/binary.sha256"
sha256sum "$SRC/src/colmap/util/version.cc" > "$EVID/version-cc.sha256"

# Per-object MVS device-code inventory (expected SASS86/89, PTX70/90, no sm120).
for object in patch_match_cuda gpu_mat_prng gpu_mat_ref_image; do
  obj="$BUILD/src/colmap/mvs/CMakeFiles/colmap_mvs_cuda.dir/${object}.cu.o"
  test -f "$obj"
  cuobjdump --list-elf "$obj" > "$EVID/mvs/${object}.elf.txt"
  cuobjdump --list-ptx "$obj" > "$EVID/mvs/${object}.ptx.txt"
  sha256sum "$obj" >> "$EVID/mvs/object-sha256.txt"
done

echo "built control ${NAME} -> ${PREFIX}"
