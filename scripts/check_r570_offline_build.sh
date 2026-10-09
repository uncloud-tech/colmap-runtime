#!/usr/bin/env bash
# Run inside the image as a non-root UID with --network none and writable /workspace.
set -euo pipefail
[ "$(id -u)" != 0 ]
export HOME=/workspace/home TMPDIR=/workspace/tmp CCACHE_DIR=/workspace/ccache
mkdir -p "$HOME" "$TMPDIR" "$CCACHE_DIR" /workspace/src
sha256sum -c /opt/photogram-dev/evidence/source-archive.sha256
tar -xzf /opt/archives/colmap-c6.tar.gz --strip-components=1 -C /workspace/src
cmake -S /workspace/src -B /workspace/build -GNinja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/workspace/out/install \
  -DCMAKE_PREFIX_PATH=/opt/deps -DBOOST_ROOT=/opt/deps \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
  '-DCMAKE_CUDA_ARCHITECTURES=86-real;89-real;120-real;70-virtual' \
  -DCUDA_ENABLED=ON -DHIP_ENABLED=OFF -DMVS_ENABLED=ON \
  -DGUI_ENABLED=OFF -DOPENGL_ENABLED=OFF -DONNX_ENABLED=OFF \
  -DCGAL_ENABLED=OFF -DCASPAR_ENABLED=OFF -DLSD_ENABLED=ON \
  -DTESTS_ENABLED=ON -DBUILD_SHARED_LIBS=OFF -DCCACHE_ENABLED=OFF \
  -DFETCH_BOOST=OFF -DFETCH_POSELIB=OFF -DFETCH_FAISS=OFF -DFETCH_ONNX=OFF \
  -DFETCHCONTENT_FULLY_DISCONNECTED=ON -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build /workspace/build --parallel "$(nproc)" --target colmap_mvs_mat_test
ctest --test-dir /workspace/build --no-tests=error --output-on-failure -R '^mvs/mat_test$'
