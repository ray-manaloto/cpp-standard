# The base image layer (environment-standard.md section 3, D45, D49): Ubuntu by digest, mise
# installed by packslip with mise's signer key (D73), and the apt packages of the three apt
# fragments through `mise bootstrap` (D75). Every FROM comes from a build argument holding a
# digest, never a tag; `mise run artifact:build base` passes them from image/base.inputs.toml.
# The build context holds only the files of the base hash (python/pins/pins.py tag base --inputs).
ARG PACKSLIP_IMAGE
ARG UBUNTU_IMAGE
FROM ${PACKSLIP_IMAGE} AS packslip

FROM ${UBUNTU_IMAGE}
ARG MISE_VERSION
ARG MISE_SIGNER
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# packslip checks mise's signature and publisher before it extracts it, so no install script
# runs (the mise cookbook's Docker recipe); its CA bundle serves packslip until apt installs
# ca-certificates.
COPY --from=packslip /packslip /usr/local/bin/packslip
COPY --from=packslip /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
RUN packslip install github.com/jdx/mise --version "$MISE_VERSION" --pin "$MISE_SIGNER" \
    && mise --version

# mise runs plain `apt-get install -y`; the image installs no recommended packages.
RUN printf 'APT::Install-Recommends "false";\nAPT::Install-Suggests "false";\n' \
      >/etc/apt/apt.conf.d/90-no-recommends

WORKDIR /opt/cppstd
COPY .mise/conf.d/apt-sources.toml .mise/conf.d/apt-toolchain-host.toml .mise/conf.d/apt.toml \
     .mise/conf.d/

# apt reads TLS roots from /usr/lib/ssl, which the Ubuntu image lacks until the openssl and
# ca-certificates packages are installed; without them apt refuses apt.llvm.org's certificate
# and skips that source. So ca-certificates goes in first, from the Ubuntu archive (signed
# indexes over http) at its apt.toml pin, before `mise bootstrap` adds the https source.
RUN version="$(sed -n 's/^"apt:ca-certificates" = { version = "\([^"]*\)".*/\1/p' .mise/conf.d/apt.toml)" \
    && test -n "$version" \
    && apt-get update \
    && apt-get install -y --no-install-recommends "ca-certificates=$version" \
    && rm -rf /var/lib/apt/lists/*

# D104: the first base build re-checks that mise reads the fragments as the schema writes them
# (`mise config ls`) and that nothing the fragments name is missing afterwards
# (`status --missing` exits 0). dpkg-query prints the versions installed.
# The fragments are trusted for these commands only, so the image sets no mise environment.
RUN export MISE_TRUSTED_CONFIG_PATHS=/opt/cppstd MISE_CEILING_PATHS=/opt \
    && mise config ls \
    && mise bootstrap --skip tools --yes \
    && echo "D104: mise bootstrap packages status --missing" \
    && mise bootstrap packages status --missing \
    && echo "D104 PASS: every bootstrap package is installed" \
    && dpkg-query -W g++-16 clang-23 llvm-23 libclang-rt-23-dev git \
    && rm -rf /var/lib/apt/lists/*
