#!/usr/bin/env bash
# Static per-object check. The external check_dev_targets.py additionally
# matches every sm89 SASS kernel entry against compute90 PTX before publication.
# PR8 requests 89-real;120-real globally; the upstream MVS workaround emits
# 89-real;90-virtual. Blackwell execution uses driver PTX-JIT, not sm120 MVS SASS.
set -euo pipefail
BUILD="${1:-/opt/src/colmap-pr8/build}"
command -v cuobjdump >/dev/null || { echo 'cuobjdump not found' >&2; exit 1; }
mapfile -t objects < <(find "$BUILD/src/colmap/mvs/CMakeFiles/colmap_mvs_cuda.dir" -type f -name '*.cu.o' | sort)
(( ${#objects[@]} == 3 )) || { echo 'Expected three MVS CUDA objects' >&2; exit 1; }
for object in "${objects[@]}"; do
  elf="$(cuobjdump --list-elf "$object")"
  ptx="$(cuobjdump --dump-ptx "$object")"
  grep -q 'sm_89' <<< "$elf" || { echo "FAIL: missing sm89 SASS: $object" >&2; exit 1; }
  grep -Eq '^[[:space:]]*\.target[[:space:]]+sm_90' <<< "$ptx" || { echo "FAIL: missing compute90 PTX: $object" >&2; exit 1; }
  if grep -Eq 'sm_100|sm_120' <<< "$elf"; then
    echo "FAIL: unexpected Blackwell MVS SASS: $object" >&2; exit 1
  fi
  echo "PASS: $object: sm89 SASS + compute90 PTX"
done
echo 'GPU execution/JIT NOT tested; per-kernel coverage is gated externally.'
