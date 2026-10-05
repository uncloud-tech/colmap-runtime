#!/usr/bin/env bash
# Read-only exact-parent observation. No installation, downloads, or resolution.
# INSPECTION_ROOT exists only for local fixture tests; CI leaves it unset.
set -euo pipefail
ROOT="${INSPECTION_ROOT:-}"
EXPECTED_SHA=5a91882290532b2719eaca77c0f3a7448bd73b9214e56df57bc59004560a80c6
printf 'architecture=%s\nPATH=%s\nLD_LIBRARY_PATH=%s\n' \
  "$(uname -m)" "$PATH" "${LD_LIBRARY_PATH:-<unset>}"
printf 'inspection_scope=PATH plus /usr/bin,/bin,/usr/local,/usr/lib,/opt; maxdepth=8; max128 interpreters\n'
roots=()
for directory in /usr/bin /bin /usr/local /usr/lib /opt; do
  if [ -d "$ROOT$directory" ]; then roots+=("$ROOT$directory"); fi
done
candidates=()
if (( ${#roots[@]} )); then
  mapfile -t candidates < <(find "${roots[@]}" -maxdepth 8 \
    \( -type f -o -type l \) \
    \( -name python -o -name python3 -o -name 'python3.[0-9]*' -o -name pypy -o -name pypy3 \) \
    ! -name '*-config' -print | sort -u)
fi
# Also inspect commands resolved on the image's actual PATH, not the host PATH
# when local fixtures provide INSPECTION_ROOT.
if [ -z "$ROOT" ]; then
  for name in python python3 python3.14 pypy pypy3; do
    if path="$(command -v "$name")"; then candidates+=("$path"); fi
  done
fi
declare -A seen=()
interpreters=()
for candidate in "${candidates[@]}"; do
  [ -x "$candidate" ] || continue
  canonical="$(readlink -f "$candidate")"
  [ -f "$canonical" ] || continue
  printf 'python_alias=%s -> %s\n' "$candidate" "$canonical"
  if [ -z "${seen[$canonical]:-}" ]; then
    seen[$canonical]=1
    interpreters+=("$canonical")
  fi
done
printf 'python_candidates=%s\n' "${#interpreters[@]}"
matched=no
count=0
for executable in "${interpreters[@]}"; do
  count=$((count + 1))
  if (( count > 128 )); then echo 'interpreter_inventory_truncated=yes'; break; fi
  printf 'python_executable=%s\n' "$executable"
  sha="$(sha256sum "$executable")"; sha="${sha%% *}"
  printf 'python_executable_sha256=%s\n' "$sha"
  if version="$(timeout 20 "$executable" --version 2>&1)"; then
    printf 'python_version=%s\n' "$version"
    if [ "$sha" = "$EXPECTED_SHA" ] && [ "$version" = 'Python 3.14.7' ]; then matched=yes; fi
  else
    printf 'python_version=unconfirmed (execution failed)\n'
  fi
  if ! timeout 30 "$executable" -I -B -c '
import json, sys, sysconfig, importlib.util
try:
    from importlib import metadata
    distributions = sorted({(d.metadata["Name"], d.version) for d in metadata.distributions()})
except ImportError:
    distributions = None
pip = importlib.util.find_spec("pip")
wanted = {"contourpy":"1.4.0", "cuda-toolkit":"12.9.2.0", "cycler":"0.12.1", "fonttools":"4.65.0", "kiwisolver":"1.5.1", "matplotlib":"3.11.2", "numpy":"2.5.3", "nvidia-cuda-runtime-cu12":"12.9.79", "nvidia-curand-cu12":"10.3.10.19", "packaging":"26.3", "pillow":"12.3.0", "pycolmap-cuda12":"4.2.0", "pyparsing":"3.3.2", "python-dateutil":"2.9.0.post0", "scipy":"1.18.1", "six":"1.17.0"}
import re
installed = {re.sub(r"[-_.]+", "-", n).lower(): v for n,v in (distributions or [])}
missing = {n:v for n,v in wanted.items() if installed.get(n) != v}
print(json.dumps({"executable":sys.executable, "version_info":list(sys.version_info), "implementation":sys.implementation.name, "prefix":sys.prefix, "base_prefix":sys.base_prefix, "soabi":sysconfig.get_config_var("SOABI"), "sys_path":sys.path, "site_packages":sysconfig.get_paths().get("purelib"), "pip_module":None if pip is None else pip.origin, "distributions":None if distributions is None else distributions[:256], "distributions_truncated":distributions is not None and len(distributions)>256, "locked16_missing_or_mismatched":missing, "locked_wheel_bytes":"unconfirmed"},sort_keys=True))
'; then
    echo 'python_runtime_inventory=unconfirmed (unsupported or failed interpreter)'
  fi
  if ! timeout 20 "$executable" -I -B -m pip --version; then
    echo 'pip_execution=absent_or_unconfirmed (see preceding result)'
  fi
done
printf 'locked_interpreter_match=%s\n' "$matched"
if [ "$matched" = no ]; then
  echo 'reuse_assessment=no verified exact locked CPython3.14.7 interpreter in inspected scope'
else
  echo 'reuse_assessment=exact interpreter candidate; locked distribution bytes/libraries still require verification'
fi
if (( ${#roots[@]} )); then
  echo 'site_package_directories_begin'
  find "${roots[@]}" -maxdepth 8 -type d \( -name site-packages -o -name dist-packages \) -print | sort -u
  echo 'site_package_directories_end'
fi
if [ -x "$ROOT/opt/colmap-pr8/bin/colmap" ]; then
  sha256sum "$ROOT/opt/colmap-pr8/bin/colmap"
  ldd "$ROOT/opt/colmap-pr8/bin/colmap"
else
  echo 'native_binary=absent in fixture/inspected root'
fi
echo 'Observation only; no global filesystem-absence, dependency-byte equivalence, or GPU claim.'
