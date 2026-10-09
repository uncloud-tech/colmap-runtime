#!/usr/bin/env bash
# Stable entrypoint for the R570.195.03 / CUDA 12.8 development image.
#
#   docker run --rm <image> [<cmd> [args...]]
#
# Before any governed run it verifies the identity of BOTH named controls
# (stock and seed) against baked hashes.  It never puts a colmap binary on
# PATH: callers must select /opt/colmap-stock/bin/colmap or
# /opt/colmap-seed/bin/colmap explicitly, so an ambiguous/stale "colmap" can
# never be executed by accident.
set -euo pipefail
sha256sum --status -c /opt/photogram-dev/controls/stock.sha256
sha256sum --status -c /opt/photogram-dev/controls/seed.sha256

if command -v colmap >/dev/null 2>&1; then
  echo "FAIL: a 'colmap' binary is on PATH; select /opt/colmap-stock or /opt/colmap-seed explicitly" >&2
  exit 1
fi

case "${1:-}" in
  doctor|prepare|gpu-smoke)
    exec /usr/local/bin/photogram-dev "$@" ;;
  photogram-dev)
    shift
    exec /usr/local/bin/photogram-dev "$@" ;;
esac

if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec bash
