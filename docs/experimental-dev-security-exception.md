# Temporary experimental dev image: approved header exception

## Owner decision, 2026-10-01

The owner approved updating GnuPG and accepting header findings for the
experimental dev image, with no production data and deletion after confirming
benchmarks. Nsight may be installed separately if profiling is needed; the
bundled Nsight Compute is omitted from this image. This supersedes the proposed
encrypted-artifact-only handoff; that handoff was never dispatched.

This is explicit, scoped risk acceptance, **not a zero-vulnerability claim** and
not a production exception. Production `scripts/check_security.py` and its
workflow are unchanged.

## Scope enforced by scripts/check_dev_security.py

- Exact CUDA base image:
  `nvidia/cuda:12.8.1-devel-ubuntu24.04@sha256:4b9ed5fa8361736996499f64ecebf25d4ec37ff56e4d11323ccde10aa36e0c43`.
  The Dockerfile records the same build argument used by `FROM` in the baked
  manifest; missing/ambiguous base identity fails closed. A different base does
  not receive the header exception.
- On 2026-10-04 the owner approved applying the same narrow exception to PR8
  and binding it to the base digest instead of the COLMAP source commit. This
  is a scope clarification for the identical base/package finding, not an
  expiry extension or a waiver of other HIGH/CRITICAL findings.
- Ubuntu 24.04 OS-package result, package `linux-libc-dev`, installed version
  `6.8.0-55.57` only. No kernel-image, kernel-module, user-space package, bundled
  Go binary, other version or ecosystem receives this exception.
- New gate invocations stop accepting these findings on **2026-10-15 UTC**.
  This deadline does not automatically delete an already published image.
- Every accepted CVE remains individually recorded in `security-gate.json`, with
  raw severity counts and `zero_high_critical: false` when findings are accepted.
- Other HIGH/CRITICAL findings still block. Scan/parse/identity failures block.
- No full CPU-suite, standalone sanitizer, GPU execution or driver-JIT validation
  is implied by the image's selected CPU/static-architecture checks.

`linux-libc-dev` supplies development UAPI headers, not the booted host kernel.
The package is required by compiler development dependencies and remains
installed. Acceptance does not constitute a host-kernel vulnerability assessment.
Background: https://lists.ubuntu.com/archives/kernel-team/2024-February/148886.html

## Container-only remediation

GnuPG packages move from `2.4.4-2ubuntu17` to the current stable Noble candidate
`2.4.4-2ubuntu17.6`, exceeding the reported fix floor `.17.4`. Verified 2026-10-01
against Noble-updates/main and universe amd64 package indices at
https://archive.ubuntu.com/ubuntu/dists/noble-updates/ . All ten affected binary
packages are explicitly versioned; unexpected unavailability fails the build.

Exactly `cuda-nsight-compute-12-8` and `nsight-compute-2025.1.1` are purged after
checking apt's removal plan, with no autoremove. This removes ncu/Nsight profiling,
including the vulnerable EFA nic_sampler binary, from the final filesystem.
CUDA nvcc12.8.93, cuobjdump12.8.90 and compute-sanitizer12.8.93 remain. No host
packages/drivers change. Later Nsight installation must be version-recorded and
its own vulnerabilities/driver compatibility assessed.

A final stage reuses the cached dependency and COLMAP build. It checks byte
identity of the COLMAP binary and required CUDA tools and version identity of
headers, libc/libstdc++ and CUDA tool packages before/after remediation. Candidate
and future controls retain the same compiler headers. The image's final-stage
update does not touch `/opt/deps`, source, kernel flags or architecture workaround.
Package-manager removal is not layer squashing: original base-layer bytes can
still exist in the image archive even though the final filesystem omits Nsight.

## Evidence / retirement

The image contains `/opt/colmap-dev/EXPERIMENTAL-USE.txt` plus remediation package
and binary-preservation records, also copied to workflow artifacts. Existing CPU,
installed-header and per-MVS SASS/PTX gates still must pass before publication.
The workflow records a revision/run-specific registry tag and immutable digest.

Use only for the confirming experiments; never promote to production or mount
production data/credentials. After benchmarks, identify and delete the exact
published GHCR version, remove local copies and close the exception. No registry
version is deleted automatically by this change. Build caches and previous CI
artifacts have separate retention and may retain layers; clean those only with
owner-approved scoped cleanup, never unrelated images or protected experiments.
