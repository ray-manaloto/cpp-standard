# The project build (environment-standard.md section 4): the stand-in module and
# the core module, built on three compilers through the presets in
# cmake/presets/. Dependencies come from vcpkg's manifest (vcpkg.json) through
# the toolchain file the presets name.
cmake_minimum_required(VERSION 4.5)
# `import std` is stable in CMake 4.5; the core module uses it.
set(CMAKE_CXX_MODULE_STD ON)
project(cpp_standard LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 26)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# The gcov of the preset's compiler; `mise run ci` reads it from the cache for
# the coverage step.
set(CPPSTD_GCOV
    ""
    CACHE STRING "gcov executable for the coverage step")

enable_testing()

add_subdirectory(src)
add_subdirectory(tests)
