# The project build (environment-standard.md section 4). The tracer bullet
# (#125) builds only the stand-in module; M1a PR 4 adds cmake/probes.cmake,
# the core module and fixtures/must-fail/, and raises the minimum to 4.5
# with the tools image. Until then the gate runs the CMake of the Ubuntu
# container (4.3).
cmake_minimum_required(VERSION 4.3)
project(cpp_standard LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 26)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# The gcov of the preset's compiler; `mise run ci` reads it from the cache
# for the coverage step.
set(CPPSTD_GCOV "" CACHE STRING "gcov executable for the coverage step")

enable_testing()

add_subdirectory(src)
add_subdirectory(tests)
