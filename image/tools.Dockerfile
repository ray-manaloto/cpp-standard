# The tools image layer (environment-standard.md section 3, D45, D74): the base image and the
# tools of .mise/conf.d/tools.toml, installed system-wide from the committed lock, plus a non-root
# user. Toolchains are not baked in; toolchain:fetch installs them in each job (D72, D83).
# BASE_IMAGE is ghcr.io/ray-manaloto/cpp-standard/base@sha256:<digest>, never a tag. `mise run
# artifact:build tools` passes it, and supplies that reference from the base build's own OCI
# layout (a named build context), so the build needs no registry.
# The build context holds only the files of the tools hash (python/pins/pins.py tag tools --inputs).
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# System installs live under /usr/local/share/mise (mise install --system); as root there is no
# sudo to call.
ENV MISE_SYSTEM_PACKAGES_SUDO=false \
    PATH=/usr/local/share/mise/shims:$PATH

WORKDIR /opt/cppstd
COPY .mise/conf.d/tools.toml .mise/conf.d/
# mise writes the lock with mode 600; the image's user must read it.
COPY --chmod=644 .mise/mise.lock .mise/mise.lock
COPY .mise/locks/ .mise/locks/
RUN export MISE_TRUSTED_CONFIG_PATHS=/opt/cppstd MISE_CEILING_PATHS=/opt \
    && mise install --system --locked \
    && mise reshim --system \
    && mise ls \
    && cmake --version && ninja --version && gcovr --version && g++-16 --version

# The non-root user. uid 1001 is the hosted runner's, so a container job can write the
# workspace it mounts.
RUN groupadd --gid 1001 cppstd \
    && useradd --create-home --uid 1001 --gid 1001 --shell /bin/bash cppstd
USER 1001:1001
WORKDIR /home/cppstd
