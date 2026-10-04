#!/usr/bin/env bash
# Combined STANDALONE ASan+UBSan of the sweep_tile selector/layout test ONLY —
# NOT a full COLMAP sanitizer rebuild — plus an optimized standalone build.
# Usage: build-asan.sh [source-dir] [out-dir]
set -euo pipefail
SRC="${1:-/opt/src/colmap-pr8}"
OUT="${2:-/work/build}"
mkdir -p "$OUT"
TEST="$SRC/src/colmap/mvs/sweep_tile_test.cc"
[ -f "$TEST" ] || { echo "no sweep_tile_test.cc under $SRC" >&2; exit 2; }

# Combined address+undefined sanitizer, standalone mode (per agreed recipe).
g++ -std=c++17 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
    -DCOLMAP_SWEEP_STANDALONE -I"$SRC/src" "$TEST" -o "$OUT/sweep_tile_test.asan-ubsan"

# Optimized standalone (no sanitizer).
g++ -std=c++17 -O2 -DNDEBUG -DCOLMAP_SWEEP_STANDALONE -I"$SRC/src" "$TEST" \
    -o "$OUT/sweep_tile_test.opt"

ls -l "$OUT"/sweep_tile_test.* 2>/dev/null || true
{
  echo "standalone_sanitizer=g++ -std=c++17 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer -DCOLMAP_SWEEP_STANDALONE"
  echo "standalone_optimized=g++ -std=c++17 -O2 -DNDEBUG -DCOLMAP_SWEEP_STANDALONE"
  echo "asan_ubsan_sha256=$(sha256sum "$OUT/sweep_tile_test.asan-ubsan" | awk '{print $1}')"
  echo "opt_sha256=$(sha256sum "$OUT/sweep_tile_test.opt" | awk '{print $1}')"
  echo "expected_checks_each=131272128"
} | tee "$OUT/SANITIZER-MANIFEST.txt"
