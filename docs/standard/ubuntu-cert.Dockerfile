# The Ubuntu 26.10 container (amd64 and arm64) that docs/standard/ubuntu.md certifies.
# A stand-in until the M1a base and tools images exist (D45, D49, D73):
# the same base digest and toolchain sources, with every package pinned to the
# exact version the playbook was run against. apt.llvm.org deletes old
# snapshots within days (D12), so a rebuild after that needs new LLVM pins;
# the image ID in the report header is the record of what was certified.
# Build: mise run certify:ubuntu-image: amd64 on the PC's Docker, or with --local
# arm64 on the Mac's Docker Desktop. Each arch-specific download is picked by
# TARGETARCH and checked against its own digest.
# The LLVM 23 snapshot every stage installs from (declared before the first
# FROM so the IWYU stage sees it too).
# Bumped 2026-11-16 from the c47d7823685a snapshot, which apt.llvm.org had
# already deleted (D12). LLVM23_COMMIT is the same snapshot's full commit,
# for the llvm23-offload stage's sources; that stage checks the two agree.
ARG LLVM_VER=1:23.1.6~++20261115084239+551bf48cf74f-1~exp1~20261115204336.95
ARG LLVM23_COMMIT=551bf48cf74f5aa587924a38f2cb29f72e7c9497
FROM ubuntu:26.10@sha256:b5194b8e58989da0865ebc80078bf9f5f8742ec6a867c53f6ae699f6036756f7 AS base
LABEL org.opencontainers.image.base.digest=sha256:b5194b8e58989da0865ebc80078bf9f5f8742ec6a867c53f6ae699f6036756f7
LABEL org.cpp-standard.cert=1

ARG LLVM_VER
# apt.llvm.org's signing key, checked by fingerprint (M0 (f)).
ARG LLVM_SIGNER_FPR=6084F3CF814B57C1CF12EFD515CF4D18AF4F7421
ARG MISE_VER=2026.11.8
ARG MISE_SHA256_AMD64=d2d5a46f507bba772686e2c8f2316b3a4439dac49a37a30db5c0e7bb077c5431
ARG MISE_SHA256_ARM64=b36da3c4892380325d44dee3678ba618de191254d8a4aed8011ee66b28a6cbd7
ARG TARGETARCH

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
      gcc-16-offload-nvptx=16.2.0-3ubuntu1 nvptx-tools=0.20260402-1 \
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
      libomp-23-dev="$LLVM_VER" liboffload-23="$LLVM_VER" liboffload-23-dev="$LLVM_VER" \
    && rm -rf /var/lib/apt/lists/*

# mise from its release tarball, checked by digest. A stand-in for D73's packslip install.
RUN case "$TARGETARCH" in amd64) a=x64 h="$MISE_SHA256_AMD64" ;; arm64) a=arm64 h="$MISE_SHA256_ARM64" ;; *) exit 1 ;; esac \
    && curl -fsSLo /tmp/mise.tar.gz \
      "https://github.com/jdx/mise/releases/download/v${MISE_VER}/mise-v${MISE_VER}-linux-${a}.tar.gz" \
    && echo "${h}  /tmp/mise.tar.gz" | sha256sum -c - \
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
# BUILD_JOBS caps ninja (empty: its default); the Mac build passes 4.
ARG BUILD_JOBS
RUN apt-get update && apt-get install -y --no-install-recommends \
      llvm-23-dev="$LLVM_VER" libclang-23-dev="$LLVM_VER" libclang-cpp23-dev="$LLVM_VER" \
    && rm -rf /var/lib/apt/lists/*
RUN git init -q /src && git -C /src fetch -q --depth 1 https://github.com/include-what-you-use/include-what-you-use "$IWYU_COMMIT" \
    && git -C /src checkout -q FETCH_HEAD && test "$(git -C /src rev-parse HEAD)" = "$IWYU_COMMIT" \
    && cmake -G Ninja -S /src -B /b -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=/usr/lib/llvm-23 \
         -DCMAKE_C_COMPILER=clang-23 -DCMAKE_CXX_COMPILER=clang++-23 -DCMAKE_INSTALL_PREFIX=/opt/iwyu-llvm23 \
    && ninja -C /b ${BUILD_JOBS:+-j"$BUILD_JOBS"} install

# The OpenMP NVPTX device runtime for clang 23 (GPU offload, D136 amended
# 2026-11-16): neither apt.llvm.org (no nvptx64-nvidia-cuda files in any
# llvm-23 package) nor the 23.1.5 release tarball ships it. Built from the
# apt snapshot's own commit with the apt clang-23, as a standalone runtimes
# build (openmp/docs/Building.md "Building with Offload Support").
FROM base AS llvm23-offload
ARG LLVM_VER
ARG LLVM23_COMMIT
ARG BUILD_JOBS
RUN [[ "$LLVM_VER" == *"+${LLVM23_COMMIT:0:12}-"* ]] \
    && apt-get update && apt-get install -y --no-install-recommends \
      llvm-23-dev="$LLVM_VER" libclang-23-dev="$LLVM_VER" libclang-cpp23-dev="$LLVM_VER" \
    && rm -rf /var/lib/apt/lists/*
RUN git init -q /src && git -C /src remote add origin https://github.com/llvm/llvm-project \
    && git -C /src fetch -q --depth 1 --filter=blob:none origin "$LLVM23_COMMIT" \
    && git -C /src sparse-checkout set --no-cone /runtimes /openmp /offload /cmake /llvm/cmake \
         /llvm/utils/llvm-lit /llvm/utils/lit /libc/shared /third-party \
    && git -C /src checkout -q FETCH_HEAD && test "$(git -C /src rev-parse HEAD)" = "$LLVM23_COMMIT" \
    && cmake -G Ninja -S /src/runtimes -B /b -DCMAKE_BUILD_TYPE=Release \
         -DLLVM_ENABLE_RUNTIMES=openmp -DLLVM_DEFAULT_TARGET_TRIPLE=nvptx64-nvidia-cuda \
         -DCMAKE_C_COMPILER=clang-23 -DCMAKE_CXX_COMPILER=clang++-23 \
         -DCMAKE_C_COMPILER_TARGET=nvptx64-nvidia-cuda -DCMAKE_CXX_COMPILER_TARGET=nvptx64-nvidia-cuda \
         -DCMAKE_C_COMPILER_WORKS=ON -DCMAKE_CXX_COMPILER_WORKS=ON \
         -DLLVM_BINARY_DIR=/usr/lib/llvm-23 -DLLVM_ENABLE_PER_TARGET_RUNTIME_DIR=ON \
         -DCMAKE_INSTALL_PREFIX=/opt/llvm23-offload \
    && ninja -C /b ${BUILD_JOBS:+-j"$BUILD_JOBS"} install \
    && test -f /opt/llvm23-offload/lib/nvptx64-nvidia-cuda/libomptarget-nvptx.bc

# NVIDIA's CUDA redistributables, for clang's GPU offload (ptxas, nvlink,
# fatbinary, libdevice; cuda.h only so clang can read the version). Each
# archive is checked against the sha256 in NVIDIA's redistrib_<ver>.json, and
# only what clang uses is kept. Two toolkits: clang 23 takes 13.2 (the newest
# it fully supports, clang/include/clang/Basic/Cuda.h:54); p2996 takes 12.9,
# because CUDA 13's ptxas writes the new ELF SM encoding that LLVM 21 cannot
# read (llvm/lib/Object/ELFObjectFile.cpp:684 "Unknown EF_CUDA_SM value").
# Neither is on PATH.
FROM base AS cuda
ARG CUDA_REDIST=https://developer.download.nvidia.com/compute/cuda/redist
# VERSION:SHA256-linux-x86_64:SHA256-linux-sbsa (arm64). On arm64 the toolkits
# are there for compiling, but GO is N/A: no GPU reaches Docker on the Mac.
ARG TARGETARCH
ARG CUDA13_NVCC=13.2.86:b04e5ca5b41f8b5629ce5f16930920e6af437f32c9777fcb67e0361f732b6f43:0ae0716074fb8ca9a2eaebb0acd1425d8a41904ace1320793bbad270c3ce043f
ARG CUDA13_NVVM=13.2.86:029fc2a43904a2208a83dfd5834c4c343394d1117279f849863ae94208a88b8a:14eb9d4d180f8466b3eb25e6801f48b7790b614a19528b876ec5d1b98abf05a1
ARG CUDA13_CUDART=13.2.86:d6be2b3546fa93e5dec9e3d118d31f9540d0b7af5319ee3c6726f202dfc5b5d4:30d07b79d832b517cedced78a9e1aa63ebfaa8d71e4df6d1943cdf33fe563400
ARG CUDA12_NVCC=12.9.86:7a1a5b652e5ef85c82b721d10672fc9a2dbaab44e9bd3c65a69517bf53998c35:0aa1fce92dbae76c059c27eefb9d0ffb58e1291151e44ff7c7f1fc2dd9376c0d
ARG CUDA12_CUDART=12.9.79:1f6ad42d4f530b24bfa35894ccf6b7209d2354f59101fd62ec4a6192a184ce99:8b422a3b2cb8452cb678181b0bf9d7aa7342df168b5319c5488ae3b8514101fc
# get PREFIX PACKAGE VERSION:SHA-X86_64:SHA-SBSA fetches one archive, checks it, unpacks it.
RUN case "$TARGETARCH" in amd64) p=linux-x86_64 ;; arm64) p=linux-sbsa ;; *) exit 1 ;; esac \
    && get() { \
      local v h f h_x h_s; IFS=: read -r v h_x h_s <<<"$3"; \
      if [[ "$p" == linux-x86_64 ]]; then h="$h_x"; else h="$h_s"; fi; \
      f="$2-$p-$v-archive"; \
      curl -fsSLo "/tmp/$f.tar.xz" "$CUDA_REDIST/$2/$p/$f.tar.xz" \
        && echo "$h  /tmp/$f.tar.xz" | sha256sum -c - \
        && mkdir -p "$1" && tar -C "$1" --strip-components=1 -xJf "/tmp/$f.tar.xz" && rm "/tmp/$f.tar.xz"; \
    } \
    && get /tmp/c13 cuda_nvcc "$CUDA13_NVCC" && get /tmp/c13 libnvvm "$CUDA13_NVVM" \
    && get /tmp/c13 cuda_cudart "$CUDA13_CUDART" \
    && get /tmp/c12 cuda_nvcc "$CUDA12_NVCC" && get /tmp/c12 cuda_cudart "$CUDA12_CUDART" \
    && for p in 13.2:c13 12.9:c12; do \
         d="/opt/cuda-${p%%:*}" s="/tmp/${p#*:}"; \
         mkdir -p "$d/bin" "$d/nvvm" \
         && cp "$s"/bin/ptxas "$s"/bin/nvlink "$s"/bin/fatbinary "$d/bin/" \
         && cp -r "$s/include" "$d/" && cp -r "$s/nvvm/libdevice" "$d/nvvm/" && cp "$s/LICENSE" "$d/" \
         || exit 1; \
       done \
    && rm -rf /tmp/c13 /tmp/c12 && du -sh /opt/cuda-13.2 /opt/cuda-12.9

FROM base
ARG TARGETARCH
ARG CLANGD_SHA256_AMD64=f72edb0b36580ece7f52e23858f00c18fad4e87395ea7ad05d7e55c39f8fc78a
ARG CLANGD_SHA256_ARM64=44f1e4b7a125b2763d56386a199928dd57ec32e151cc6042dce2f7b0da7bb651
# clangd: apt.llvm.org's clangd-23 needs libabsl20260107, which 26.10 does not
# have (E2). Until a stonking suite exists, clangd comes from the nearest LLVM
# release tarball, checked against GitHub's published digest.
# Unpacked to /opt/llvm-23.1.5 on both architectures.
RUN case "$TARGETARCH" in amd64) t=LLVM-23.1.5-Linux-X64 h="$CLANGD_SHA256_AMD64" ;; \
      arm64) t=LLVM-23.1.5-Linux-ARM64 h="$CLANGD_SHA256_ARM64" ;; *) exit 1 ;; esac \
    && curl -fsSLo /tmp/llvm.tar.xz \
      "https://github.com/llvm/llvm-project/releases/download/llvmorg-23.1.5/${t}.tar.xz" \
    && echo "${h}  /tmp/llvm.tar.xz" | sha256sum -c - \
    && mkdir /opt/llvm-23.1.5 \
    && tar -C /opt/llvm-23.1.5 --strip-components=1 -xJf /tmp/llvm.tar.xz "${t}/bin/clangd" "${t}/lib/clang" \
    && rm /tmp/llvm.tar.xz
COPY --from=iwyu /opt/iwyu-llvm23/ /opt/iwyu-llvm23/
RUN ln -s /opt/iwyu-llvm23/bin/include-what-you-use /usr/local/bin/include-what-you-use \
    && ln -s /opt/iwyu-llvm23/bin/iwyu_tool.py /usr/local/bin/iwyu_tool.py \
    && ln -s /opt/iwyu-llvm23/bin/fix_includes.py /usr/local/bin/fix_includes.py \
    && include-what-you-use --version
COPY --from=cuda /opt/cuda-13.2/ /opt/cuda-13.2/
COPY --from=cuda /opt/cuda-12.9/ /opt/cuda-12.9/
COPY --from=llvm23-offload /opt/llvm23-offload/ /opt/llvm23-offload/
# clang 23 finds the device runtime in <its dir>/../lib/<triple>
# (clang/lib/Driver/ToolChains/CommonArgs.cpp:3076-3078), so no flag is needed.
RUN ln -s /opt/llvm23-offload/lib/nvptx64-nvidia-cuda /usr/lib/llvm-23/lib/nvptx64-nvidia-cuda
