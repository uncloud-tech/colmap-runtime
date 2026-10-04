# TEMPORARY DEV image: build/test ENVIRONMENT for COLMAP PR#8, with the exact
# commissioned tree prebuilt. CPU-built only — NOT production, NOT
# GPU-validated.
#
# Offline/reproducible model (per coordinator): ALL dependencies are acquired and
# installed into a shared immutable prefix (/opt/deps) in a NETWORK-ENABLED stage;
# COLMAP is then configured/built with FETCH_*=OFF, explicit dependency paths, and
# --network=none, so nothing is fetched opportunistically during configure/build.
#
# - Base: CUDA 12.8.1 / Ubuntu 24.04 (amd64 digest 4b9ed5fa...). NOT 12.9: the
#   5090 path needs PTX-JIT and 12.9 PTX may exceed driver 570.195.03's JIT support.
# - MVS target (workaround-aware): global "89-real;120-real" yields native sm_89
#   SASS + compute_90 PTX (the workaround drops sm_100+ from MVS).
# - GUI/ONNX OFF explicitly. Tests ON (GTest+GMock) for the CPU host tests.
# - The dependency prefix is shared with optional offline control builds.
ARG CUDA_BASE_IMAGE=nvidia/cuda:12.8.1-devel-ubuntu24.04@sha256:4b9ed5fa8361736996499f64ecebf25d4ec37ff56e4d11323ccde10aa36e0c43
FROM ${CUDA_BASE_IMAGE} AS toolchain
ARG CUDA_BASE_IMAGE
# pipefail so a failed command in a RUN pipeline fails the step (hadolint DL4006).
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG COLMAP_COMMIT=340f78310590cefda7cd3bb61ff0775ae5e2b59f
ARG COLMAP_TARBALL_SHA256=350f219ff4c07f68a9a834e0838d280d1a7f45884e0aa97182229401fe58695e
ARG BOOST_VERSION=1.92.0
ARG BOOST_SHA256=9bed76128d4e46755dbe818487788c6fceb6f72b378f4daa49b7e1e600d9088d
ARG PARENT_COMMIT=78f41b8c6cb2629775115ee2dc3b50f21a51c4f1
ARG PARENT_TARBALL_SHA256=9f132c88a3b2b8b6b8680c5eff4a20dc1dbd96fe2da1f47f4356c5d5aedb8575
ARG POSELIB_COMMIT=1bb8881f08e68f0b3d9b2ecc411fc15e7766ef1b
ARG POSELIB_SHA256=ee46322581c7901fe24e91434eeec27163f820d481cba5faa43d37651fabc8e8
ARG FAISS_VERSION=1.14.1
ARG FAISS_SHA256=4b1ae7e7a0a46385b4084f0e3945623a15fcf99d793bf44d82aae8e24f11e5f5
ARG GTEST_COMMIT=063de7e9578f82b369302001269680b4b1553359
ARG GTEST_SHA256=623fe05d283020f37a579a8985ba338091ac7229da62b5591ff40acdf05b95e2
ARG CUDA_ARCHITECTURES="89-real;120-real"

ENV DEBIAN_FRONTEND=noninteractive
LABEL org.opencontainers.image.description="DEV build/test env: COLMAP PR#8; CPU-built, offline deps, not GPU-validated"
LABEL org.uncloud.colmap.source.commit="${COLMAP_COMMIT}"

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git cmake ninja-build build-essential ccache unzip xz-utils \
        libeigen3-dev libceres-dev libgoogle-glog-dev libgflags-dev libfreeimage-dev libmetis-dev \
        libopenimageio-dev openimageio-tools libsqlite3-dev libcurl4-openssl-dev \
        libssl-dev libglew-dev libgtest-dev libgmock-dev \
        libopenblas-dev liblapack-dev \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /usr/include/opencv4 /opt/deps /opt/src /opt/colmap-dev /opt/archives /work/src /work/build /work/opt

# Exported runtime libraries of the shared deps + COLMAP install, so the built
# binaries/tests resolve them offline (no network, no host installs).
ENV LD_LIBRARY_PATH=/opt/deps/lib:/opt/colmap-pr8/lib
ENV PATH=/opt/colmap-pr8/bin:${PATH}
# Benchmark-only opt-in; callers may explicitly set 1 for seed-0 geometric runs.
ENV COLMAP_PATCH_MATCH_COMPACT_PRNG=0

# ---- ACQUIRE + INSTALL pinned deps into the shared prefix /opt/deps (network) ----
RUN set -eux; \
    curl -fsSL "https://github.com/google/googletest/archive/${GTEST_COMMIT}.tar.gz" -o /tmp/gtest.tar.gz; \
    echo "${GTEST_SHA256}  /tmp/gtest.tar.gz" | sha256sum -c -; \
    mkdir -p /tmp/gtest-src; tar -xzf /tmp/gtest.tar.gz -C /tmp/gtest-src --strip-components=1; \
    cmake -S /tmp/gtest-src -B /tmp/gtest-build -GNinja -DCMAKE_BUILD_TYPE=Release \
          -DCMAKE_CXX_STANDARD=17 -DCMAKE_INSTALL_PREFIX=/opt/deps -DBUILD_GMOCK=ON -DINSTALL_GTEST=ON; \
    cmake --build /tmp/gtest-build -j"$(nproc)"; cmake --install /tmp/gtest-build; rm -rf /tmp/gtest-*; \
    \
    curl -fsSL "https://github.com/boostorg/boost/releases/download/boost-${BOOST_VERSION}/boost-${BOOST_VERSION}-cmake.tar.xz" -o /tmp/boost.tar.xz; \
    echo "${BOOST_SHA256}  /tmp/boost.tar.xz" | sha256sum -c -; \
    mkdir -p /tmp/boost-src; tar -xf /tmp/boost.tar.xz -C /tmp/boost-src --strip-components=1; \
    cmake -S /tmp/boost-src -B /tmp/boost-build -GNinja -DCMAKE_BUILD_TYPE=Release \
          -DCMAKE_INSTALL_PREFIX=/opt/deps \
          -DBOOST_INCLUDE_LIBRARIES="graph;program_options;system;algorithm;container_hash;heap;preprocessor;property_map;property_tree;unordered;utility;asio;functional;next_prior;predef" \
          -DBOOST_ENABLE_MPI=OFF -DBOOST_ENABLE_PYTHON=OFF -DBOOST_INSTALL_LAYOUT=system; \
    cmake --build /tmp/boost-build -j"$(nproc)"; cmake --install /tmp/boost-build; rm -rf /tmp/boost-*; \
    \
    curl -fsSL "https://github.com/PoseLib/PoseLib/archive/${POSELIB_COMMIT}.zip" -o /tmp/poselib.zip; \
    echo "${POSELIB_SHA256}  /tmp/poselib.zip" | sha256sum -c -; \
    unzip -q /tmp/poselib.zip -d /tmp/poselib-src; \
    cmake -S "/tmp/poselib-src/PoseLib-${POSELIB_COMMIT}" -B /tmp/poselib-build -GNinja \
          -DCMAKE_BUILD_TYPE=Release -DMARCH_NATIVE=OFF -DCMAKE_INSTALL_PREFIX=/opt/deps; \
    cmake --build /tmp/poselib-build -j"$(nproc)"; cmake --install /tmp/poselib-build; rm -rf /tmp/poselib-*; \
    \
    curl -fsSL "https://github.com/facebookresearch/faiss/archive/refs/tags/v${FAISS_VERSION}.zip" -o /tmp/faiss.zip; \
    echo "${FAISS_SHA256}  /tmp/faiss.zip" | sha256sum -c -; \
    unzip -q /tmp/faiss.zip -d /tmp/faiss-src; \
    cmake -S "/tmp/faiss-src/faiss-${FAISS_VERSION}" -B /tmp/faiss-build -GNinja \
          -DCMAKE_BUILD_TYPE=Release -DFAISS_ENABLE_GPU=OFF -DFAISS_ENABLE_PYTHON=OFF \
          -DFAISS_ENABLE_MKL=OFF -DFAISS_OPT_LEVEL=dd -DBUILD_TESTING=OFF -DCMAKE_INSTALL_PREFIX=/opt/deps; \
    cmake --build /tmp/faiss-build -j"$(nproc)"; cmake --install /tmp/faiss-build; rm -rf /tmp/faiss-*; \
    \
    curl -fsSL "https://codeload.github.com/uncloud-tech/colmap/tar.gz/${COLMAP_COMMIT}" -o /tmp/colmap.tar.gz; \
    echo "${COLMAP_TARBALL_SHA256}  /tmp/colmap.tar.gz" | sha256sum -c -; \
    mkdir -p /opt/src/colmap-pr8; tar -xzf /tmp/colmap.tar.gz -C /opt/src/colmap-pr8 --strip-components=1; \
    rm -f /tmp/colmap.tar.gz; \
    git -C /opt/src/colmap-pr8 init -q; git -C /opt/src/colmap-pr8 add -A; \
    git -C /opt/src/colmap-pr8 -c user.email=dev@local -c user.name=dev commit -qm "colmap PR#8 ${COLMAP_COMMIT}"

# Bake the EXACT parent (78f41b8c) archive so controls build fully offline from a
# LOCAL verified tarball (sha enforced) with its own writable tree.
RUN mkdir -p /opt/archives && \
    curl -fsSL "https://codeload.github.com/uncloud-tech/colmap/tar.gz/${PARENT_COMMIT}" \
        -o "/opt/archives/colmap-parent-${PARENT_COMMIT}.tar.gz" && \
    echo "${PARENT_TARBALL_SHA256}  /opt/archives/colmap-parent-${PARENT_COMMIT}.tar.gz" | sha256sum -c - && \
    mkdir -p /opt/src/colmap-parent && \
    tar -xzf "/opt/archives/colmap-parent-${PARENT_COMMIT}.tar.gz" -C /opt/src/colmap-parent --strip-components=1

# Record the immutable dependency/toolchain manifest (source/dep hashes, toolchain).
RUN { echo "image=colmap-dev"; echo "source_repo=https://github.com/uncloud-tech/colmap"; \
      echo "base_image=${CUDA_BASE_IMAGE}"; \
      echo "source_commit=${COLMAP_COMMIT}"; echo "source_tarball_sha256=${COLMAP_TARBALL_SHA256}"; \
      echo "boost_version=${BOOST_VERSION}"; echo "boost_sha256=${BOOST_SHA256}"; \
      echo "poselib_commit=${POSELIB_COMMIT}"; echo "poselib_sha256=${POSELIB_SHA256}"; \
      echo "faiss_version=${FAISS_VERSION}"; echo "faiss_sha256=${FAISS_SHA256}"; \
      echo "gtest_commit=${GTEST_COMMIT}"; echo "gtest_sha256=${GTEST_SHA256}"; \
      echo "cuda_architectures=${CUDA_ARCHITECTURES}"; echo "onnx=OFF"; echo "gui=OFF"; echo "tests=ON"; \
      echo "dep_prefix=/opt/deps"; \
      echo "platform=$(uname -s -m)"; \
      echo "cmake=$(cmake --version | head -1)"; \
      echo "nvcc=$(nvcc --version | tail -1)"; \
      echo "cuda=$(tr -d '\n ' < /usr/local/cuda/version.json 2>/dev/null || echo unknown)"; \
      echo "ccache=$(ccache --version | head -1)"; \
      echo "compute_sanitizer=$(ls -1 /usr/local/cuda/bin/compute-sanitizer 2>/dev/null || echo MISSING)"; \
    } > /opt/colmap-dev/BUILD-MANIFEST.txt

# ---- COLMAP configure/build: OFFLINE (no network), explicit dep paths ----
FROM toolchain AS dev-pr8
ARG CUDA_ARCHITECTURES="89-real;120-real"
RUN --network=none cmake -S /opt/src/colmap-pr8 -B /opt/src/colmap-pr8/build -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCUDA_ENABLED=ON -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHITECTURES}" \
        -DONNX_ENABLED=OFF -DGUI_ENABLED=OFF -DCGAL_ENABLED=OFF -DLSD_ENABLED=OFF \
        -DCASPAR_ENABLED=OFF -DBUILD_SHARED_LIBS=OFF -DTESTS_ENABLED=ON \
        -DFETCH_BOOST=OFF -DFETCH_POSELIB=OFF -DFETCH_FAISS=OFF -DFETCH_ONNX=OFF \
        -DCMAKE_PREFIX_PATH=/opt/deps -DBOOST_ROOT=/opt/deps \
        -DCMAKE_INSTALL_PREFIX=/opt/colmap-pr8 && \
    cmake --build /opt/src/colmap-pr8/build -j"$(nproc)" && \
    cmake --install /opt/src/colmap-pr8/build

# Append the EXACT executed Release/CUDA flags (shared across all arms) and the
# runtime-library resolution to the manifest, so the flags are auditable.
RUN { echo "--- executed build flags ---"; \
      echo "cmake_build_type=Release"; \
      echo "cuda_architectures=${CUDA_ARCHITECTURES}"; \
      grep -m1 '^CMAKE_CXX_FLAGS:' /opt/src/colmap-pr8/build/CMakeCache.txt || true; \
      grep -m1 '^CMAKE_CUDA_FLAGS:' /opt/src/colmap-pr8/build/CMakeCache.txt || true; \
      echo "ld_library_path=${LD_LIBRARY_PATH}"; \
      fast_math="$(grep -m1 'use_fast_math' /opt/src/colmap-pr8/build/CMakeCache.txt || true)"; \
      if [ -n "$fast_math" ]; then echo "fast_math=on"; else echo "fast_math=off"; fi; \
    } >> /opt/colmap-dev/BUILD-MANIFEST.txt

# Identity is computed from THIS installed binary, never from a previous host.
# Runtime tile selection stays in the upstream CLI; no tile compiler override.
RUN set -eu; \
    colmap patch_match_stereo -h > /opt/colmap-dev/patch-match-help.txt 2>&1; \
    grep -q -- '--PatchMatchStereo.sweep_tile' /opt/colmap-dev/patch-match-help.txt; \
    sha256sum /opt/colmap-pr8/bin/colmap > /opt/colmap-dev/colmap.sha256; \
    binary_sha="$(awk '{print $1}' /opt/colmap-dev/colmap.sha256)"; \
    echo "binary_sha256=${binary_sha}" >> /opt/colmap-dev/BUILD-MANIFEST.txt; \
    printf '{"schema_version":1,"source_repo":"https://github.com/uncloud-tech/colmap","source_commit":"%s","source_tarball_sha256":"%s","binary_path":"/opt/colmap-pr8/bin/colmap","binary_sha256":"%s","cuda_architectures":"%s","mvs_cuda_architectures":"89-real;90-virtual","sweep_tile_option":"--PatchMatchStereo.sweep_tile","sweep_tile_values":[0,8,16,32],"compact_prng_default":"0"}\n' \
        "$COLMAP_COMMIT" "$COLMAP_TARBALL_SHA256" "$binary_sha" "$CUDA_ARCHITECTURES" \
        > /opt/colmap-dev/image-contract.json

# Stable entrypoint + unprivileged operation (harness runs as UID 1002).
COPY build-variant.sh verify-targets.sh entrypoint.sh build-asan.sh /opt/colmap-dev/
COPY patches/ /opt/colmap-dev/patches/
RUN chmod +x /opt/colmap-dev/*.sh \
    && chmod -R a+rX /opt/colmap-pr8 /opt/colmap-dev /opt/deps /opt/src /opt/archives \
    && chmod -R 0777 /work
ENTRYPOINT ["/opt/colmap-dev/entrypoint.sh"]

# Final container-only security remediation. Preserve cached compilation and
# compiler headers identically for candidate and on-demand controls.
# Owner approved linux-libc-dev header findings for this disposable experiment;
# that exception does NOT cover GnuPG or the bundled Nsight Go executable.
FROM dev-pr8 AS dev-experimental
ARG GNUPG_VERSION=2.4.4-2ubuntu17.6
RUN set -eux; \
    mkdir -p /opt/colmap-dev/security-remediation; \
    sha256sum /opt/colmap-pr8/bin/colmap /usr/local/cuda/bin/nvcc \
        /usr/local/cuda/bin/cuobjdump /usr/local/cuda/bin/compute-sanitizer \
        > /opt/colmap-dev/security-remediation/retained-binaries.sha256; \
    dpkg-query -W -f='${Package} ${Version}\n' linux-libc-dev libc6 libc6-dev libstdc++6 libgcc-s1 \
        cuda-nvcc-12-8 cuda-cuobjdump-12-8 cuda-sanitizer-12-8 \
        > /opt/colmap-dev/security-remediation/retained-packages.before; \
    apt-get update; \
    apt-get -s purge cuda-nsight-compute-12-8 nsight-compute-2025.1.1 \
        > /opt/colmap-dev/security-remediation/nsight-removal-plan.txt; \
    cat /opt/colmap-dev/security-remediation/nsight-removal-plan.txt; \
    awk '/^(Remv|Purg) / { if ($2 != "cuda-nsight-compute-12-8" && $2 != "nsight-compute-2025.1.1") exit 1; n++ } END { if (n != 2) exit 1 }' \
        /opt/colmap-dev/security-remediation/nsight-removal-plan.txt; \
    apt-get -y -o APT::Get::AutomaticRemove=false purge cuda-nsight-compute-12-8 nsight-compute-2025.1.1; \
    apt-get install -y --no-remove --only-upgrade --no-install-recommends \
        "dirmngr=${GNUPG_VERSION}" "gnupg=${GNUPG_VERSION}" "gnupg-utils=${GNUPG_VERSION}" \
        "gnupg2=${GNUPG_VERSION}" "gpg=${GNUPG_VERSION}" "gpg-agent=${GNUPG_VERSION}" \
        "gpgconf=${GNUPG_VERSION}" "gpgsm=${GNUPG_VERSION}" "gpgv=${GNUPG_VERSION}" "keyboxd=${GNUPG_VERSION}"; \
    rm -rf /var/lib/apt/lists/*; \
    test ! -e /opt/nvidia/nsight-compute/2025.1.1/host/target-linux-x64/plugins/efa_metrics/nic_sampler; \
    test ! -e /usr/local/cuda/bin/ncu; \
    sha256sum -c /opt/colmap-dev/security-remediation/retained-binaries.sha256; \
    dpkg-query -W -f='${Package} ${Version}\n' linux-libc-dev libc6 libc6-dev libstdc++6 libgcc-s1 \
        cuda-nvcc-12-8 cuda-cuobjdump-12-8 cuda-sanitizer-12-8 \
        > /opt/colmap-dev/security-remediation/retained-packages.after; \
    cmp /opt/colmap-dev/security-remediation/retained-packages.before /opt/colmap-dev/security-remediation/retained-packages.after; \
    dpkg-query -W -f='${Package} ${Version}\n' dirmngr gnupg gnupg-utils gnupg2 gpg gpg-agent gpgconf gpgsm gpgv keyboxd \
        > /opt/colmap-dev/security-remediation/gnupg-packages.txt; \
    /usr/local/cuda/bin/nvcc --version; \
    /usr/local/cuda/bin/cuobjdump --version; \
    /usr/local/cuda/bin/compute-sanitizer --version; \
    printf '%s\n' 'EXPERIMENTAL DEV ONLY; NO PRODUCTION DATA.' \
        'Owner-approved linux-libc-dev header exception on 2026-10-01; expires 2026-10-15.' \
        'Delete this image after confirming benchmarks; no production promotion.' \
        'GnuPG updated; Nsight Compute omitted (may be installed separately for profiling).' \
        > /opt/colmap-dev/EXPERIMENTAL-USE.txt
LABEL org.opencontainers.image.description="TEMPORARY experimental COLMAP PR8 dev image; no production data; accepted header findings; delete after confirming benchmarks"
