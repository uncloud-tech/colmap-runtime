FROM nvidia/cuda@sha256:1199283a7fd5fc7dcb472ea4c6b6d8eb378ef8c0b9aae5e731491c01a219ca43 AS base
# pipefail so a failed command in a RUN pipeline fails the step (hadolint
# DL4006). Declared per stage because each FROM may start with a fresh shell.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
LABEL org.opencontainers.image.source="https://github.com/uncloud-tech/colmap-runtime"
LABEL org.opencontainers.image.description="Pinned CUDA-enabled PyCOLMAP runtime; GPU validation requires a separate test"

# Weekly base-package freshness bound. BuildKit layer/registry caching would
# otherwise reuse this apt layer indefinitely. A value that changes each ISO
# week forces the base stage to re-resolve Ubuntu security updates while the
# independent pycolmap-builder/babelstream stages (and the COLMAP source
# compile) stay cached. Only the base stage's packages ship in the runtime
# image, so the build-only stages are deliberately not busted.
ARG APT_REFRESH=unset

RUN echo "APT_REFRESH=${APT_REFRESH}" && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get -o APT::Get::Always-Include-Phased-Updates=true upgrade -y && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates curl openssh-server libsm6 libice6 libx11-6 libxext6 \
    libgl1 libopengl0 libglib2.0-0t64 libgomp1 libstdc++6 \
    libboost-program-options1.83.0 libboost-graph1.83.0 libboost-system1.83.0 \
    libceres4t64 libgoogle-glog0v6t64 libgflags2.2 \
    libfreeimage3 libmetis5 libopenimageio2.4t64 libsqlite3-0 \
    libcurl4t64 libssl3t64 libglew2.2 && \
    dpkg-query -W -f='${binary:Package} ${db:Status-Status}\n' > /tmp/runtime-package-status && \
    awk '$2 == "installed" && $1 ~ /-dev(:[^ ]+)?$/ { print "ERROR: runtime development package: " $1; bad=1 } END { exit bad }' /tmp/runtime-package-status && \
    rm -f /tmp/runtime-package-status && \
    rm -rf /var/lib/apt/lists/* && mkdir -p /run/sshd /opt/colmap-runtime && \
    ssh-keygen -A
ENV PATH="/opt/colmap-runtime/python/bin:${PATH}" \
    PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LD_LIBRARY_PATH="/opt/colmap-runtime/python/lib/python3.14/site-packages/nvidia/cuda_runtime/lib:/opt/colmap-runtime/python/lib/python3.14/site-packages/nvidia/curand/lib:/usr/local/nvidia/lib:/usr/local/nvidia/lib64:/usr/local/cuda/lib64"

# ---------------------------------------------------------------------------
# Source-built PyCOLMAP with per-worker CUDA streams (benchmark-v4 option C).
#
# The published `pycolmap-cuda12` wheel cannot express a per-instance CUDA
# stream nor remove the shared module-scope `__constant__ ref_K/ref_inv_K`
# calibration, so the MVS CUDA sources are patched and PyCOLMAP is rebuilt with
# CUDA. The pinned COLMAP 4.2.0 tarball and the patch are both hash-checked
# before use; the patch is the exact byte-for-byte file published with the
# benchmark-v4 job package. Device targets mirror the BabelStream stage:
# sm_70/75/86/89/120. COLMAP's own CMake workaround (issue #3514) drops sm_100+
# SASS for the MVS target and emits sm_90 PTX instead, so sm_120 is still
# requested here and JIT-compiled on Blackwell at first launch.
#
# This stage is CPU-validated only (nvcc + cmake run without a GPU); kernel
# execution and reconstruction quality require the separate GPU canary.
# ---------------------------------------------------------------------------
FROM nvidia/cuda@sha256:020bc241a628776338f4d4053fed4c38f6f7f3d7eb5919fecb8de313bb8ba47c AS pycolmap-builder
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG COLMAP_VERSION=4.2.0
ARG COLMAP_TARBALL_SHA256=b61731fb1a4a33609e64fb353fe589d483be6a73878a5965b7d32ae23fb22fc5
ARG COLMAP_PATCH_SHA256=c0ebc12088595049b070e00363df6ad23b0087c61a99c36660b1e7316d65dcce
ENV DEBIAN_FRONTEND=noninteractive
# openimageio-tools supplies /usr/bin/iconvert etc.: Ubuntu's
# OpenImageIOConfig.cmake exports imported executable targets and CMake refuses
# to configure if their files are absent. libopenimageio-dev alone does not
# install them, so COLMAP's find_package(OpenImageIO) fails without this.
# Ubuntu's OpenImageIO config also hardcodes the OpenCV include dir in its
# INTERFACE_INCLUDE_DIRECTORIES even though COLMAP uses none of OIIO's OpenCV
# functionality, so an empty /usr/include/opencv4 must exist (the same fix as
# COLMAP's own docs/CI).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git cmake ninja-build build-essential \
        libboost-program-options-dev libboost-graph-dev libboost-system-dev \
        libeigen3-dev libceres-dev libgoogle-glog-dev libgflags-dev \
        libfreeimage-dev libmetis-dev libopenimageio-dev openimageio-tools \
        libsqlite3-dev \
        libcurl4-openssl-dev libssl-dev libglew-dev && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /usr/include/opencv4
# Pinned CPython 3.14.7 (the same archive the runtime builder installs), used
# only to build the wheel; it is not copied into the final image.
RUN curl --fail --location --retry 3 \
    https://github.com/astral-sh/python-build-standalone/releases/download/20260924/cpython-3.14.7+20260924-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz \
    -o /opt/python.tar.gz && \
    echo 'bd0d0568ccded07bbf1c87727230dc5dd0187e706a87da23c4de78388a229b78  /opt/python.tar.gz' | sha256sum -c - && \
    mkdir -p /opt/pybuild && tar -xzf /opt/python.tar.gz -C /opt/pybuild && rm /opt/python.tar.gz && \
    /opt/pybuild/python/bin/python3.14 -m ensurepip && \
    /opt/pybuild/python/bin/python3.14 -m pip install --no-cache-dir \
        'scikit-build-core>=0.3.3' 'pybind11==3.1.0' numpy
COPY patch_match_cuda.2streams.patch /build/patch_match_cuda.2streams.patch
WORKDIR /build
RUN echo "${COLMAP_TARBALL_SHA256}  colmap.tar.gz" > /tmp/sums && \
    echo "${COLMAP_PATCH_SHA256}  patch_match_cuda.2streams.patch" >> /tmp/sums && \
    curl --fail --location --retry 3 \
        "https://codeload.github.com/colmap/colmap/tar.gz/refs/tags/${COLMAP_VERSION}" -o colmap.tar.gz && \
    sha256sum -c /tmp/sums && \
    mkdir source && tar -xzf colmap.tar.gz -C source --strip-components=1 && \
    patch -d source -p1 < /build/patch_match_cuda.2streams.patch && \
    cmake -S source -B source/build -GNinja -DCMAKE_BUILD_TYPE=Release \
        -DCUDA_ENABLED=ON -DCMAKE_CUDA_ARCHITECTURES="70;75;86;89;120" \
        -DGUI_ENABLED=OFF -DCGAL_ENABLED=OFF -DLSD_ENABLED=OFF \
        -DONNX_ENABLED=OFF -DCASPAR_ENABLED=OFF -DBUILD_SHARED_LIBS=OFF \
        -DCMAKE_INSTALL_PREFIX=/opt/colmap && \
    cmake --build source/build -j"$(nproc)" && cmake --install source/build
# Build the pycolmap wheel against the patched, installed COLMAP. Stub
# generation is disabled so no extra stub tooling is required.
# Override Python's build-time clang preference inherited by scikit-build-core;
# use the installed GNU toolchain, matching the COLMAP libraries above.
RUN mkdir -p /opt/wheels && \
    CC=/usr/bin/gcc CXX=/usr/bin/g++ \
    /opt/pybuild/python/bin/python3.14 -m pip wheel /build/source \
        --no-build-isolation --no-deps --wheel-dir /opt/wheels \
        --config-settings=cmake.define.colmap_DIR=/opt/colmap/share/colmap \
        --config-settings=cmake.define.GENERATE_STUBS=OFF && \
    ls -l /opt/wheels

FROM base AS builder
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY runtime-lock.json requirements.lock THIRD_PARTY_NOTICES.md /opt/colmap-runtime/
# benchmark-v4: the source-built, patched PyCOLMAP wheel (produced by the
# pycolmap-builder stage) replaces the pinned pycolmap wheel.
COPY --from=pycolmap-builder /opt/wheels/ /opt/colmap-runtime/pycolmap-wheel/
RUN curl --fail --location --retry 3 \
    https://github.com/astral-sh/python-build-standalone/releases/download/20260924/cpython-3.14.7+20260924-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz \
    -o /opt/colmap-runtime/python.tar.gz && \
    echo 'bd0d0568ccded07bbf1c87727230dc5dd0187e706a87da23c4de78388a229b78  /opt/colmap-runtime/python.tar.gz' | sha256sum -c - && \
    tar -xzf /opt/colmap-runtime/python.tar.gz -C /opt/colmap-runtime && rm /opt/colmap-runtime/python.tar.gz
RUN (python3.14 -m pip --version || python3.14 -m ensurepip) && \
    python3.14 -m pip --isolated install --no-cache-dir --no-deps --require-hashes \
      --only-binary=:all: --index-url https://pypi.org/simple -r /opt/colmap-runtime/requirements.lock && \
    python3.14 -m pip --isolated install --no-cache-dir --no-deps --no-index \
      --find-links /opt/colmap-runtime/pycolmap-wheel pycolmap==4.2.0 && \
    python3.14 -m pip check && \
    rm -rf /opt/colmap-runtime/python/lib/python3.14/site-packages/pip \
           /opt/colmap-runtime/python/lib/python3.14/site-packages/pip-*.dist-info \
           /opt/colmap-runtime/python/lib/python3.14/ensurepip \
           /opt/colmap-runtime/pycolmap-wheel && \
    rm -f /opt/colmap-runtime/python/bin/pip*
COPY verify_runtime.py /opt/colmap-runtime/verify_runtime.py


# Measured GPU provenance: BabelStream (the GPU counterpart of STREAM) for
# per-device memory bandwidth. Pinned, unmodified upstream source compiled here;
# its licence requires published results to follow the run rules, so the
# measurement records array size, iterations and thread/device count and the
# binary is not patched. `nvidia/nvbandwidth` for host<->device throughput is a
# follow-up (Apache-2.0); it needs cmake and Boost, so it is deliberately not in
# this stage yet.
FROM nvidia/cuda@sha256:020bc241a628776338f4d4053fed4c38f6f7f3d7eb5919fecb8de313bb8ba47c AS babelstream
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG BABELSTREAM_SHA256=63aab1bc42a1e953dcae26e279ab100866f8491ab5ce7167269f2ca4b16bb2fb
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl cmake make g++ && rm -rf /var/lib/apt/lists/*
WORKDIR /build
# BabelStream v5.0's CUDA model ignores CMAKE_CUDA_ARCHITECTURES: it requires
# CUDA_ARCH and CMAKE_CUDA_COMPILER and emits exactly one nvcc `-arch=` (see
# src/cuda/model.cmake). `-arch=sm_86` also embeds compute_86 PTX, and the other
# rented families are added as extra --generate-code entries so one binary carries
# native SASS for every GPU this launcher rents: Volta (7.0), Turing (7.5),
# Ampere (8.6), Ada (8.9) and Blackwell (12.0). Volta and Turing matter for the
# memory-bandwidth axis: a V100 has ~900 GB/s HBM2 and a T4 ~320 GB/s, and CUDA
# 12.9 still supports building for both (they become unsupported in the next
# major toolkit). Without these entries the measured bandwidth figure is simply
# absent on those hosts. GPU device code is fixed at build time and never tuned
# for the build host; the CUDA base is pinned to 12.9.1, the same CUDA version as
# the runtime base.
#
# Host ISA portability (incident 2026-09-29). BabelStream v5.0's top-level
# CMakeLists.txt sets `DEFAULT_RELEASE_FLAGS -O3 -march=native` (line 49) and
# applies it to every translation unit of the target, including the
# g++-compiled src/main.cpp and nvcc's host side. An unpinned build therefore
# adopts the build host's ISA: the GitHub runner has AVX-512, so the a9d97999
# image carried AVX-512 host instructions that SIGILL (rc 132) right after the
# header on every rented host without AVX-512 (Broadwell Xeon E5 v4, EPYC Zen2),
# silently dropping the GPU-bandwidth figure. `RELEASE_FLAGS` is BabelStream's
# documented override for that default; it is set to `-O3;-march=x86-64-v2` (the
# SSE4.2 x86-64 baseline every amd64 host this launcher rents supports). This
# replaces `-march=native` for host code in both languages while leaving the
# CUDA device targets above untouched. The objdump check after the build scans
# the host disassembly for zmm registers, mask registers, EVEX broadcast/zero
# markers and EVEX-only mnemonics, and fails the stage if any survive. (It does
# not scan for the raw EVEX 0x62 prefix: literal data inside .text also contains
# 0x62 bytes -- e.g. the ASCII "ble" in "available" -- which would false-fail.)
# BabelStream v5.0 names its target `$(MODEL)-stream` (the README documents
# `./build/<model>-stream`), so the CUDA build produces `build/cuda-stream`; it is
# installed under the launcher's fixed /usr/local/bin/babelstream path.
RUN curl --fail --location --retry 3 https://api.github.com/repos/UoB-HPC/BabelStream/tarball/v5.0 -o babelstream.tar.gz \
 && echo "$BABELSTREAM_SHA256  babelstream.tar.gz" | sha256sum -c - \
 && mkdir source && tar -xzf babelstream.tar.gz -C source --strip-components=1 \
 && cmake -S source -B build -DMODEL=cuda \
      -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc -DCUDA_ARCH=sm_86 \
      -DCUDA_EXTRA_FLAGS="-gencode=arch=compute_70,code=sm_70 -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_89,code=sm_89 -gencode=arch=compute_120,code=sm_120" \
      -DCMAKE_BUILD_TYPE=Release \
      -DRELEASE_FLAGS="-O3;-march=x86-64-v2" \
 && cmake --build build -j"$(nproc)" \
 && if objdump -d build/cuda-stream | grep -Eq '%zmm|zmm[0-9]|%k[0-7]|\{z\}|1to[0-9]|vpxord|vpxorq|vmovdqu(8|16|32|64)|vpmovm2|vpmov(b2m|d2m|q2m|w2m)|vpternlog[qd]|vpermi2|vpermt2|vpcompress|vpexpand|vscatter|vrcp14|vrsqrt14|vreduce|vrange|vpmadd52|vdbpsadbw|vpconflict|vplzcnt'; then \
        echo 'ERROR: babelstream host code contains AVX-512 (EVEX) instructions; it would SIGILL on non-AVX-512 hosts' >&2; \
        exit 1; \
    fi \
 && install -m 0755 build/cuda-stream /usr/local/bin/babelstream

FROM base AS runtime
COPY --from=babelstream /usr/local/bin/babelstream /usr/local/bin/babelstream
COPY --from=builder /opt/colmap-runtime /opt/colmap-runtime
RUN python3.14 /opt/colmap-runtime/verify_runtime.py --mode cpu --require-installer-free --output /opt/colmap-runtime/runtime-manifest.json && \
    dpkg-query -W > /opt/colmap-runtime/system-packages.txt && \
    python3.14 -c 'from importlib.metadata import distributions; print("\n".join(sorted(d.metadata["Name"]+"=="+d.version for d in distributions())))' > /opt/colmap-runtime/python-packages.txt

# SSH startup and authorized_keys must be configured at deployment time.
# Do not bake host keys or start SSH automatically here.
ENTRYPOINT []
CMD ["/bin/bash"]
