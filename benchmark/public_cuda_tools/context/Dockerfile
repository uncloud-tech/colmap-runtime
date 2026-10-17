# Tiny tools overlay; the accepted transport/scientific payload is inherited unchanged.
ARG BASE
FROM ${BASE} AS tools-builder
COPY acquire.py cuobjdump-lock.json LICENSE /tools-input/
COPY verify_tools.py /tools-input/verify_tools.py
ARG BASE
RUN /opt/colmap-runtime/python/bin/python3.14 /tools-input/acquire.py /tools-input /staged "$BASE"

FROM ${BASE} AS payload-base
COPY --from=tools-builder /staged/ /
ENV PATH="/usr/local/bin:${PATH}"
# No optimized CLI is baked here. A private, separately identified CLI bundle is
# inspected with this tool at the artifact gate and again before GPU execution.
