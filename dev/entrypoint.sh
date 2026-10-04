#!/usr/bin/env bash
# Stable entrypoint so the harness can run arbitrary commands:
#   docker run --rm <image> <cmd> [args...]
# With no args, drop into bash. Runs unprivileged; no docker socket needed.
set -euo pipefail
# Detect a replaced/overlaid binary before starting a governed run.
sha256sum --status -c /opt/colmap-dev/colmap.sha256
if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec bash
