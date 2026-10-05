#!/usr/bin/env bash
# Read-only native snapshot: no build, install, GPU, cache or network operations.
set -euo pipefail
export LC_ALL=C
out=${1:?empty output directory required}
mkdir -p "$out"
test -z "$(ls -A "$out")"
sha256sum -c /opt/colmap-dev/colmap.sha256
sha256sum /opt/colmap-pr8/bin/colmap > "$out/binary-sha256.txt"
printf 'PATH=%s\nLD_LIBRARY_PATH=%s\nCOLMAP_PATCH_MATCH_COMPACT_PRNG=%s\n' \
  "$PATH" "${LD_LIBRARY_PATH:-}" "${COLMAP_PATCH_MATCH_COMPACT_PRNG:?}" > "$out/native-env.txt"
printf 'COLMAP_PATCH_MATCH_COMPACT_PRNG=%s\ncolmap=%s\n' \
  "$COLMAP_PATCH_MATCH_COMPACT_PRNG" "$(command -v colmap)" > "$out/runtime-defaults.txt"
cp /opt/colmap-dev/image-contract.json /opt/colmap-dev/BUILD-MANIFEST.txt "$out/"
colmap patch_match_stereo -h > "$out/patch-match-help.txt" 2>&1
ldd /opt/colmap-pr8/bin/colmap | sed -E 's/ \(0x[0-9a-f]+\)//g' > "$out/native-library-resolution.txt"
if grep -q 'not found' "$out/native-library-resolution.txt"; then
  echo 'Native library missing' >&2; exit 1
fi
awk '{for(i=1;i<=NF;i++) if($i ~ /^\//) print $i}' "$out/native-library-resolution.txt" |
  while IFS= read -r library; do readlink -f "$library"; done | sort -u |
  while IFS= read -r library; do sha256sum "$library"; done > "$out/native-library-files.sha256"
for tool in nvcc g++ cmake ninja; do
  sha256sum "$(readlink -f "$(command -v "$tool")")"
done > "$out/native-tools.sha256"
# Native source, installed dependencies, binary/lib tree and MVS codegen objects.
find /opt/src/colmap-pr8/src /opt/deps /opt/colmap-pr8 -type f -print0 |
  sort -z | xargs -0 -r sha256sum > "$out/native-source-identity.txt"
sha256sum /opt/src/colmap-pr8/build/CMakeCache.txt >> "$out/native-source-identity.txt"
find /opt/src/colmap-pr8/build/src/colmap/mvs/CMakeFiles/colmap_mvs_cuda.dir -type f -name '*.cu.o' -print0 |
  sort -z | xargs -0 -r sha256sum >> "$out/native-source-identity.txt"
dpkg-query -W -f='${Package}\t${Version}\n' | sort > "$out/system-packages.txt"
