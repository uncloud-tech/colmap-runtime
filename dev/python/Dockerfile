# Python layer only: the immutable native parent is never recompiled.
FROM ghcr.io/uncloud-tech/colmap-runtime-dev@sha256:8993096b761a11d210afc5c49cbc8b8622d0b96d36fb539b348089c18d97ac0b AS python_install
COPY .staged/artifacts/ /input/
COPY .staged/helpers/collect_dev_python_native.sh /tmp/collect-native.sh
RUN --network=none bash /tmp/collect-native.sh /tmp/native-before
RUN --network=none printf '%s\n' 'bd0d0568ccded07bbf1c87727230dc5dd0187e706a87da23c4de78388a229b78  /input/cpython-3.14.7+20260924-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz' > /tmp/python.sha256 \
    && sha256sum -c /tmp/python.sha256 \
    && mkdir -p /opt/colmap-python \
    && tar --no-same-owner -xzf /input/cpython-3.14.7+20260924-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz --strip-components=1 -C /opt/colmap-python
COPY environment-lock.json /opt/colmap-python/environment-lock.json
COPY locked_env.py install.py verify_runtime.py /opt/colmap-python/libexec/dev/python/
COPY .staged/helpers/scripts/ /opt/colmap-python/libexec/scripts/
COPY .staged/helpers/collect_dev_python_native.sh /opt/colmap-python/libexec/collect-native.sh
# hadolint ignore=DL3003
RUN --network=none cd /opt/colmap-python/libexec \
    && /opt/colmap-python/bin/python3.14 -E -s -B -m dev.python.install --artifacts /input \
    && cp /input/license-inventory.json /opt/colmap-python/wheel-license-inventory.json

FROM ghcr.io/uncloud-tech/colmap-runtime-dev@sha256:8993096b761a11d210afc5c49cbc8b8622d0b96d36fb539b348089c18d97ac0b
COPY --from=python_install /opt/colmap-python/ /opt/colmap-python/
COPY --from=python_install /tmp/native-before/ /opt/colmap-python/native-parent/
# Trusted module cwd is temporary; final WORKDIR must remain inherited.
# hadolint ignore=DL3003
RUN --network=none ln -s /opt/colmap-python/bin/python3.14 /usr/local/bin/python \
    && ln -s /opt/colmap-python/bin/python3.14 /usr/local/bin/python3 \
    && bash /opt/colmap-python/libexec/collect-native.sh /tmp/native-after \
    && cd /opt/colmap-python/libexec \
    && MPLCONFIGDIR=/tmp/colmap-python-smoke/mpl XDG_CACHE_HOME=/tmp/colmap-python-smoke/cache \
       /opt/colmap-python/bin/python3.14 -E -s -B -m dev.python.verify_runtime --bake \
       --after /tmp/native-after --scratch /tmp/colmap-python-smoke \
    && rm -rf /tmp/native-after /tmp/colmap-python-smoke
# No ENV, ENTRYPOINT or WORKDIR override: native runtime configuration is inherited.
