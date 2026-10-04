#!/usr/bin/env bash
# Statically report and GATE the CUDA targets actually emitted in the MVS CUDA
# objects, without launching a GPU.
#
# Workaround-aware: the existing Blackwell workaround DELIBERATELY drops sm_100+
# from the MVS target, so a global CMAKE_CUDA_ARCHITECTURES="86-real;120-real"
# yields, in the MVS translation units:
#   - native sm_86 SASS   (serves the RTX 3090)
#   - compute_90 PTX      (PTX-JIT on the RTX 5090; the 5090 path REQUIRES PTX)
# => the gate REQUIRES BOTH sm_86 and compute_90 in the MVS objects, and FLAGS
#    any sm_100/sm_120 in them as unexpected. Native sm_120 MVS SASS is NOT
#    expected (other, non-MVS targets may still emit it).
#
# Coverage is checked per MVS OBJECT (translation unit); per-function symbols are
# printed best-effort and any unresolved per-kernel attribution is stated.
#
# Usage: verify-targets.sh [build-dir]
set -euo pipefail
BUILD="${1:-/src/colmap-pr3/build}"
command -v cuobjdump >/dev/null || { echo "cuobjdump not found" >&2; exit 1; }

mapfile -t OBJS < <(find "$BUILD" -path '*mvs*' -name '*.o' 2>/dev/null | sort)
[ "${#OBJS[@]}" -gt 0 ] || { echo "no MVS objects under $BUILD" >&2; exit 1; }

echo "== MVS CUDA objects: emitted arch entries (per object / translation unit) =="
for f in "${OBJS[@]}"; do
  a="$(cuobjdump --list-elf "$f" 2>/dev/null | grep -oE 'sm_[0-9]+|compute_[0-9]+' | sort -u | paste -sd, - || true)"
  printf '%-68s %s\n' "$f" "${a:-<none>}"
done

echo; echo "== per-architecture tally (MVS objects) =="
ELF="$(printf '%s\n' "${OBJS[@]}" | xargs -r -n1 cuobjdump --list-elf 2>/dev/null || true)"
printf '%s\n' "$ELF" | grep -oE 'sm_[0-9]+|compute_[0-9]+' | sort | uniq -c || true

echo; echo "== per-function symbols per MVS object (best effort) =="
for f in "${OBJS[@]}"; do
  echo "--- $f"
  cuobjdump -symbols "$f" 2>/dev/null | grep -iE 'patch_match|sweep|local_ref|init_ref|Compute|Sweep' | head -12 || true
done

echo; echo "== gate (MVS scope; workaround-aware) =="
rc=0
if printf '%s\n' "$ELF" | grep -q 'sm_86'; then
  echo "PASS: native sm_86 present (RTX 3090 served)"
else
  echo "FAIL: no sm_86 in MVS -- RTX 3090 not served"
  rc=1
fi
if printf '%s\n' "$ELF" | grep -q 'compute_90'; then
  echo "PASS: compute_90 PTX present (RTX 5090 served via PTX-JIT)"
else
  echo "FAIL: no compute_90 PTX in MVS -- 5090 path not served"
  rc=1
fi
if printf '%s\n' "$ELF" | grep -qE 'sm_100|sm_120'; then
  echo "NOTE: sm_100/sm_120 appears in MVS (unexpected per the workaround; non-fatal)"
else
  echo "OK: no sm_100/sm_120 in MVS (workaround removed them, as expected)"
fi
echo "GATE: $([ $rc -eq 0 ] && echo PASS || echo FAIL) (MVS requires BOTH sm_86 and compute_90)"
echo "LIMITATION: primary check is per-object; per-function attribution above is best-effort."
exit $rc
