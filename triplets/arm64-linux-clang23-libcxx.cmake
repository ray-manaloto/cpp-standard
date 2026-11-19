# vcpkg triplet for the clang23 build (D113). Layout after glaze-build-setup's
# x64-linux triplets
# (ray-manaloto/glaze-build-setup, triplets/); the compiler and flags come from
# the chainloaded
# toolchain file, the one the project itself builds with.
set(VCPKG_TARGET_ARCHITECTURE arm64)
set(VCPKG_CRT_LINKAGE dynamic)
set(VCPKG_LIBRARY_LINKAGE static)
set(VCPKG_CMAKE_SYSTEM_NAME Linux)
set(VCPKG_CHAINLOAD_TOOLCHAIN_FILE
    "${CMAKE_CURRENT_LIST_DIR}/../cmake/toolchains/clang23.cmake")
set(VCPKG_ENV_PASSTHROUGH CPPSTD_P2996_PREFIX)
