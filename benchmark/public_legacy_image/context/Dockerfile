# Transport-only specialization of the EXISTING successful legacy runtime.
# No science/COLMAP/CUDA rebuild. No capability or operational secret in any layer.
# Results capability is injected into a protected file ONLY at authorized launch.
ARG SDK=ghcr.io/uncloud-tech/colmap-runtime-dev@sha256:d911ef90f88ff099fc15b7e2c471acb6a5226bd7ba819a06561c36d0bc65b7cb
# Required: actual inspected key-free carrier digest from the base build.
ARG BASE
FROM ${SDK} AS transport-build
SHELL ["/bin/bash","-euo","pipefail","-c"]
RUN curl --fail --location --max-time 120 --retry 0 https://nodejs.org/dist/v24.22.0/node-v24.22.0-linux-x64.tar.xz -o /tmp/node.tar.xz \
 && echo 'cc2f601cee82d9a5a233302fe307abc600727035fd7d2c3a3571755989e95008  /tmp/node.tar.xz' | sha256sum -c - \
 && mkdir /opt/benchmark-node && tar -xf /tmp/node.tar.xz -C /opt/benchmark-node --strip-components=1 \
 && rm /tmp/node.tar.xz
ENV PATH=/opt/benchmark-node/bin:$PATH
COPY package.json package-lock.json /client/
RUN cd /client && npm ci --omit=dev --no-audit --no-fund
FROM ${BASE} AS payload-base
ARG BASE
# Keep proven root SSH/on-start service behavior. Job is staged/executed by the
# existing launcher, NOT Docker ENTRYPOINT (Vast SSH overrides it anyway).
USER 0:0
COPY --from=transport-build /opt/benchmark-node /opt/benchmark-node
COPY --from=transport-build /client/node_modules /opt/benchmark-transport/node_modules
COPY --chmod=0644 common.ts submit.ts legacy_submit.py verify_image.py LICENSE /opt/benchmark-transport/
RUN printf '%s\n' "$BASE" > /opt/benchmark-transport/carrier-image-ref
ENV PATH=/opt/benchmark-node/bin:$PATH
LABEL org.opencontainers.image.source="https://github.com/uncloud-tech/colmap-runtime" \
      org.opencontainers.image.description="Credential-free results transport overlay; legacy PyCOLMAP4.2/CUDA12.9 native bytes unchanged"
ENTRYPOINT []
CMD ["/bin/bash"]
