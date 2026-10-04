#!/usr/bin/env bash
# Build a COLMAP control variant OFFLINE from a LOCAL verified archive into its
# own writable source/build/install roots (UID1002-friendly). Never downloads.
#
# Guarantees (per agreed contract):
#  - refuses any http(s) source (offline); requires a LOCAL archive,
#  - enforces the archive SHA256 (fresh extraction; no mutation of PR source),
#  - for a patched variant: verifies the patch SHA256 and applies it with
#    `git apply --check` then `git apply` (never `patch`, never v4),
#  - configures with the IDENTICAL offline flags/dep prefix as PR#8,
#  - preserves configure/build logs, compile_commands.json, patched .cu SHA,
#    installed binary SHAs and the roots used.
#
# Usage:
#   build-variant.sh <name> <local-tarball> <expected-sha256> [patch] [patch-sha256]
# Roots (overridable env): SRC_ROOT=/work/src  BUILD_ROOT=/work/build  INSTALL_ROOT=/work/opt
set -euo pipefail
NAME="${1:?usage: build-variant.sh <name> <local-tarball> <sha256> [patch] [patch-sha256]}"
ARCHIVE="${2:?}"; SRC_SHA="${3:?}"; PATCH="${4:-}"; PATCH_SHA="${5:-}"
ARCH="${CUDA_ARCHITECTURES:-89-real;120-real}"
DEP=/opt/deps
SRC_ROOT="${SRC_ROOT:-/work/src}"
BUILD_ROOT="${BUILD_ROOT:-/work/build}"
INSTALL_ROOT="${INSTALL_ROOT:-/work/opt}"

case "$ARCHIVE" in
  http://*|https://*) echo "OFFLINE: refusing to download '${ARCHIVE}'; pass a LOCAL verified archive" >&2; exit 2 ;;
esac
[ -f "$ARCHIVE" ] || { echo "no such local archive: ${ARCHIVE}" >&2; exit 2; }

echo "${SRC_SHA}  ${ARCHIVE}" | sha256sum -c -
ROOT="${SRC_ROOT}/${NAME}"
BUILD="${BUILD_ROOT}/${NAME}-build"
PREFIX="${INSTALL_ROOT}/${NAME}"
mkdir -p "$ROOT" "$BUILD" "$PREFIX"
tar -xzf "$ARCHIVE" -C "$ROOT" --strip-components=1

if [ -n "$PATCH" ]; then
  [ -n "$PATCH_SHA" ] || { echo "patch supplied without expected sha256" >&2; exit 2; }
  echo "${PATCH_SHA}  ${PATCH}" | sha256sum -c -
  ( cd "$ROOT" && git init -q && git add -A \
      && git -c user.email=dev@local -c user.name=dev commit -qm base \
      && git apply --check "$PATCH" && git apply "$PATCH" )
fi

cmake -S "$ROOT" -B "$BUILD" -GNinja -DCMAKE_BUILD_TYPE=Release \
  -DCUDA_ENABLED=ON -DCMAKE_CUDA_ARCHITECTURES="$ARCH" \
  -DONNX_ENABLED=OFF -DGUI_ENABLED=OFF -DCGAL_ENABLED=OFF -DLSD_ENABLED=OFF -DCASPAR_ENABLED=OFF \
  -DBUILD_SHARED_LIBS=OFF -DTESTS_ENABLED=ON -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -DFETCH_BOOST=OFF -DFETCH_POSELIB=OFF -DFETCH_FAISS=OFF -DFETCH_ONNX=OFF \
  -DCMAKE_PREFIX_PATH="$DEP" -DBOOST_ROOT="$DEP" \
  -DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF -DCMAKE_EXPORT_PACKAGE_REGISTRY=OFF \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" 2>&1 | tee "$BUILD/configure.log"
cmake --build "$BUILD" -j"$(nproc)" 2>&1 | tee "$BUILD/build.log"
cmake --install "$BUILD"

{
  echo "variant=${NAME}"
  echo "archive=${ARCHIVE}"
  echo "source_sha256=${SRC_SHA}"
  if [ -n "$PATCH" ]; then echo "patch=${PATCH}"; echo "patch_sha256=${PATCH_SHA}"; fi
  echo "cuda_architectures=${ARCH}"
  echo "dep_prefix=${DEP}"
  echo "roots src=${ROOT} build=${BUILD} install=${PREFIX}"
  echo "patch_match_cuda.cu_sha256=$(sha256sum "$ROOT/src/colmap/mvs/patch_match_cuda.cu" | awk '{print $1}')"
  find "$PREFIX" \( -name '*.a' -o -name '*.so' \) -print0 2>/dev/null | xargs -0 -r sha256sum
} | tee "$BUILD/MANIFEST.txt"
echo "built ${NAME} -> ${PREFIX} ; logs+manifest in ${BUILD}"
