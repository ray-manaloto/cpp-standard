# A project container with its coding agents (D143, D147, D151). Layers:
#   1. the Ubuntu 26.10 toolchain, from `mise -E ubuntu bootstrap --from` this repository;
#   2. a non-root user, because Claude Code refuses --dangerously-skip-permissions as root;
#   3. the agent CLIs from their native installers (never mise tools), and their plugins from
#      each CLI's own commands (D147), at the latest version on every build.
# No credential is baked in. The host's agent-secrets service writes Claude Code's key and a one-hour GitHub App token
# into a folder that agents:up mounts read-only at /run/agent-secrets (D155); Codex and the Antigravity CLI keep the
# owner's own login, made once per project on each machine onto a named volume (D151).
#
# Build on the PC:  mise run agents:image      Start:  mise run agents:up <project>
# On the Mac:       mise run agents:image --host mac   and   mise run agents:up <project> --host mac
# The volumes are named per container, and Docker fills an empty named volume from the image's
# files on first use, so the plugins installed here reach the volume once. A later image does
# not refresh a volume that already exists: `mise run agents:refresh <project>` updates the CLIs
# and plugins inside a running container and keeps the logins; `agents:up --fresh` removes them.
FROM ubuntu:26.10@sha256:b5194b8e58989da0865ebc80078bf9f5f8742ec6a867c53f6ae699f6036756f7

ARG MISE_VER=2026.11.9
ARG MISE_SHA256_AMD64=23ba592fcbc61f057e2b82c1eafd085832712ba0c759b714ca16cd06babca378
ARG MISE_SHA256_ARM64=cf2900bfb4279f8d8f8a19d5c27bf1bde826b3e742182f3f67511c588498c786
# The commit to bootstrap from; agents:image passes the checkout's HEAD.
ARG CPP_STANDARD_REF=main
ARG TARGETARCH

# container=docker before any apt step: procps' postinst skips `sysctl --system` only when PID 1 has it.
ENV container=docker \
    DEBIAN_FRONTEND=noninteractive \
    MISE_DATA_DIR=/opt/mise \
    MISE_CACHE_DIR=/opt/mise/cache \
    MISE_YES=1 \
    MISE_TRUSTED_CONFIG_PATHS=/workspace \
    PATH=/opt/mise/shims:$PATH
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Layer 1: the bare minimum, mise by digest, then the toolchain module of this repository.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && case "$TARGETARCH" in amd64) a=x64 h="$MISE_SHA256_AMD64" ;; arm64) a=arm64 h="$MISE_SHA256_ARM64" ;; *) exit 1 ;; esac \
    && curl -fsSLo /tmp/mise.tar.gz \
      "https://github.com/jdx/mise/releases/download/v${MISE_VER}/mise-v${MISE_VER}-linux-${a}.tar.gz" \
    && echo "${h}  /tmp/mise.tar.gz" | sha256sum -c - \
    && tar -C /tmp -xzf /tmp/mise.tar.gz && install -m 0755 /tmp/mise/bin/mise /usr/local/bin/mise \
    && rm -rf /tmp/mise /tmp/mise.tar.gz
RUN mise -E ubuntu bootstrap --from "https://github.com/ray-manaloto/cpp-standard.git?ref=${CPP_STANDARD_REF}" \
      --from-dir /opt/cpp-standard \
    && rm -rf /var/lib/apt/lists/*

# Layer 2: the user the agents run as. Ubuntu images ship a uid 1000 user; it is renamed.
RUN if id -u ubuntu >/dev/null 2>&1; then usermod -l dev -d /home/dev -m ubuntu && groupmod -n dev ubuntu; \
    else useradd -m -u 1000 -s /bin/bash dev; fi \
    && mkdir -p /workspace && chown -R dev:dev /opt/mise /opt/cpp-standard /workspace
USER dev
WORKDIR /home/dev
ENV PATH=/home/dev/.local/bin:/home/dev/.opencode/bin:$PATH \
    CLAUDE_CONFIG_DIR=/home/dev/.claude
# Every volume mount point exists, owned by dev: Docker creates a missing one as root.
RUN mkdir -p .claude .codex .gemini .config/gh .config/opencode .local/share/opencode .local/state/opencode \
    && printf '%s\n' '{' '  "$schema": "https://opencode.ai/config.json",' \
         '  "model": "opencode/glm-5.3-flash-free",' \
         '  "compaction": { "background": false }' '}' > .config/opencode/opencode.json

# Changes on every agents:image run, so the layers below always fetch the latest releases (D152)
# while the toolchain layers above stay cached.
ARG AGENTS_CACHE_BUST=0

# Layer 3: the native installers (the same URLs as dotfiles' agents:update), then the plugins.
# The installers run without the mise shims on PATH: outside a project with a version set, a
# shim such as jq fails ("No version is set for shim") instead of falling back to the system.
RUN export PATH=/home/dev/.local/bin:/home/dev/.opencode/bin:/usr/local/bin:/usr/bin:/bin \
    && curl -fsSL https://claude.ai/install.sh | bash \
    && curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh \
    && curl -fsSL https://antigravity.google/cli/install.sh | bash \
    && curl -fsSL https://opencode.ai/v2/install | bash -s -- --no-modify-path \
    && { echo "claude $(claude --version)"; echo "codex $(codex --version)"; echo "agy $(agy --version)"; \
         echo "opencode $(opencode --version)"; } | tee /home/dev/.agent-versions
# MISE_ENV=ci adds the Linux Python and uv that the repository's own checks need (the pctools
# gate); `mise -E ubuntu bootstrap` leaves them out on purpose (mise.ci.toml).
ENV MISE_ENV=ci
RUN cd /opt/cpp-standard && mise install
# gh for pushing and pull requests (D153). Ubuntu 26.10's apt has only gh 2.46, so mise installs
# the current release for the dev user.
ARG GH_VER=2.104.0
# The doppler CLI is for the Mac's agent-secrets container (agents:up --host mac), pinned like mise.pc.toml's.
ARG DOPPLER_VER=3.77.1
RUN mise use -g "gh@${GH_VER}" "doppler@${DOPPLER_VER}"
# D155: git and gh read the App token from /run/agent-secrets at each use, so a refreshed token needs no restart;
# the shells read Claude Code's key from it at each start. ~/.local/bin is first on PATH, so the gh
# wrapper runs ahead of mise's shim, which it calls.
COPY --chmod=755 agent-auth/git-credential-agent /usr/local/bin/git-credential-agent
COPY --chmod=755 agent-auth/gh /home/dev/.local/bin/gh
COPY --chmod=644 agent-auth/profile.sh /etc/profile.d/agent-secrets.sh
# The token service itself, which the Mac runs as a container of this image (agents:up --host mac); the PC runs the
# same script as a user service.
COPY --chmod=755 agent-auth/agent-secrets.bash /usr/local/bin/agent-secrets
USER root
RUN git config --system credential.https://github.com.helper /usr/local/bin/git-credential-agent \
    && printf '\n. /etc/profile.d/agent-secrets.sh\n' >> /etc/bash.bashrc
USER dev
COPY --chmod=755 agent-plugins /usr/local/bin/agent-plugins
RUN PATH=/home/dev/.local/bin:/home/dev/.opencode/bin:/usr/local/bin:/usr/bin:/bin agent-plugins install

WORKDIR /workspace
CMD ["sleep", "infinity"]
