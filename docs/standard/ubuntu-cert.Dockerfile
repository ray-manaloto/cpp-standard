# The Ubuntu 26.10 amd64 container that docs/standard/ubuntu.md certifies.
# A stand-in until the M1a base and tools images exist (D45, D49, D73):
# the same base digest and toolchain sources, with every package pinned to the
# exact version the playbook was run against. apt.llvm.org deletes old
# snapshots within days (D12), so a rebuild after that needs new LLVM pins;
# the image ID in the report header is the record of what was certified.
# Build: mise run certify:ubuntu-image (on the Docker host, amd64 only).
# The LLVM 23 snapshot every stage installs from (declared before the first
# FROM so the IWYU stage sees it too).
ARG LLVM_VER=1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.94
FROM ubuntu:26.10@sha256:b5194b8e58989da0865ebc80078bf9f5f8742ec6a867c53f6ae699f6036756f7 AS base
LABEL org.opencontainers.image.base.digest=sha256:b5194b8e58989da0865ebc80078bf9f5f8742ec6a867c53f6ae699f6036756f7
LABEL org.cpp-standard.cert=1

ARG LLVM_VER
# apt.llvm.org's signing key, checked by fingerprint (M0 (f)).
ARG LLVM_SIGNER_FPR=6084F3CF814B57C1CF12EFD515CF4D18AF4F7421
ARG MISE_VER=2026.11.8
ARG MISE_SHA256=d2d5a46f507bba772686e2c8f2316b3a4439dac49a37a30db5c0e7bb077c5431

ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# 26.10 archive: GCC 16 (D25), binutils and make (D105), debuggers and analysers.
# Not installed: the archive `iwyu` (IWYU 0.23 on clang 19), which pulls in the
# archive `clang` package and points cc, c++ and clang++ at clang 22 (B2, T3).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates=20260816ubuntu0.26.10.2 curl=8.20.0-2ubuntu11.1 gnupg=2.4.9-4ubuntu3 \
      git=1:2.55.0-1ubuntu1.1 xz-utils=5.8.3-1ubuntu1 python3=3.14.7-3 \
      g++-16=16.2.0-3ubuntu1 gcc-16=16.2.0-3ubuntu1 binutils=2.47-6ubuntu1 make=4.4.1-3 \
      gdb=17.2-1ubuntu1 valgrind=1:3.27.1-0.2ubuntu2 linux-perf=7.3.0-10.10 cppcheck=2.21.0-1 \
    && rm -rf /var/lib/apt/lists/*

# LLVM 23 from apt.llvm.org resolute-23: 26.10 has no suite of its own (D25, D27, D105).
RUN curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key | gpg --dearmor -o /usr/share/keyrings/apt-llvm.gpg \
    && gpg --show-keys --with-colons /usr/share/keyrings/apt-llvm.gpg | grep -q "^fpr:::::::::${LLVM_SIGNER_FPR}:" \
    && echo "deb [signed-by=/usr/share/keyrings/apt-llvm.gpg] https://apt.llvm.org/resolute/ llvm-toolchain-resolute-23 main" \
       >/etc/apt/sources.list.d/llvm.list \
    && apt-get update && apt-get install -y --no-install-recommends \
      clang-23="$LLVM_VER" clang-tools-23="$LLVM_VER" llvm-23="$LLVM_VER" llvm-23-tools="$LLVM_VER" \
      libc++-23-dev="$LLVM_VER" libc++abi-23-dev="$LLVM_VER" libclang-rt-23-dev="$LLVM_VER" \
      lld-23="$LLVM_VER" lldb-23="$LLVM_VER" python3-lldb-23="$LLVM_VER" \
      clang-tidy-23="$LLVM_VER" clang-format-23="$LLVM_VER" bolt-23="$LLVM_VER" \
      libfuzzer-23-dev="$LLVM_VER" mlir-23-tools="$LLVM_VER" \
    && rm -rf /var/lib/apt/lists/*

# mise from its release tarball, checked by digest. A stand-in for D73's packslip install.
RUN curl -fsSLo /tmp/mise.tar.gz \
      "https://github.com/jdx/mise/releases/download/v${MISE_VER}/mise-v${MISE_VER}-linux-x64.tar.gz" \
    && echo "${MISE_SHA256}  /tmp/mise.tar.gz" | sha256sum -c - \
    && tar -C /tmp -xzf /tmp/mise.tar.gz && install -m 0755 /tmp/mise/bin/mise /usr/local/bin/mise \
    && rm -rf /tmp/mise /tmp/mise.tar.gz
# The tool set and its linux-x64 lock (ubuntu-cert-tools/). --locked fails the
# build if any tool or download is not in the lock.
ENV PATH=/root/.local/share/mise/shims:$PATH MISE_YES=1 \
    MISE_GLOBAL_CONFIG_FILE=/opt/cpp-standard-tools/mise.toml MISE_TRUSTED_CONFIG_PATHS=/opt/cpp-standard-tools
COPY ubuntu-cert-tools/ /opt/cpp-standard-tools/
RUN cd /opt/cpp-standard-tools && mise install --locked && mise ls --current
WORKDIR /root

# include-what-you-use for LLVM 23 (T3), built in its own stage so the LLVM
# development packages it needs stay out of the certified image. IWYU's tag
# 0.27 is the head of its clang_23 branch (c9cbc836a1af, 2026-10-04). It is
# built against the same apt.llvm.org 23.1.6 snapshot as clang-23, and finds
# the builtin headers through /usr/lib/llvm-23/bin/clang (IWYU's default).
FROM base AS iwyu
ARG LLVM_VER
ARG IWYU_COMMIT=c9cbc836a1af631610266c53cf1671b1671a0fdc
RUN apt-get update && apt-get install -y --no-install-recommends \
      llvm-23-dev="$LLVM_VER" libclang-23-dev="$LLVM_VER" libclang-cpp23-dev="$LLVM_VER" \
    && rm -rf /var/lib/apt/lists/*
RUN git init -q /src && git -C /src fetch -q --depth 1 https://github.com/include-what-you-use/include-what-you-use "$IWYU_COMMIT" \
    && git -C /src checkout -q FETCH_HEAD && test "$(git -C /src rev-parse HEAD)" = "$IWYU_COMMIT" \
    && cmake -G Ninja -S /src -B /b -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=/usr/lib/llvm-23 \
         -DCMAKE_C_COMPILER=clang-23 -DCMAKE_CXX_COMPILER=clang++-23 -DCMAKE_INSTALL_PREFIX=/opt/iwyu-llvm23 \
    && ninja -C /b install

FROM base
ARG CLANGD_TARBALL=LLVM-23.1.5-Linux-X64
ARG CLANGD_SHA256=f72edb0b36580ece7f52e23858f00c18fad4e87395ea7ad05d7e55c39f8fc78a
# clangd: apt.llvm.org's clangd-23 needs libabsl20260107, which 26.10 does not
# have (E2). Until a stonking suite exists, clangd comes from the nearest LLVM
# release tarball, checked against GitHub's published digest.
RUN curl -fsSLo /tmp/llvm.tar.xz \
      "https://github.com/llvm/llvm-project/releases/download/llvmorg-23.1.5/${CLANGD_TARBALL}.tar.xz" \
    && echo "${CLANGD_SHA256}  /tmp/llvm.tar.xz" | sha256sum -c - \
    && tar -C /opt -xJf /tmp/llvm.tar.xz "${CLANGD_TARBALL}/bin/clangd" "${CLANGD_TARBALL}/lib/clang" \
    && rm /tmp/llvm.tar.xz
COPY --from=iwyu /opt/iwyu-llvm23/ /opt/iwyu-llvm23/
RUN ln -s /opt/iwyu-llvm23/bin/include-what-you-use /usr/local/bin/include-what-you-use \
    && ln -s /opt/iwyu-llvm23/bin/iwyu_tool.py /usr/local/bin/iwyu_tool.py \
    && ln -s /opt/iwyu-llvm23/bin/fix_includes.py /usr/local/bin/fix_includes.py \
    && include-what-you-use --version
