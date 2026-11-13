# M0 (b) and (j): gcov-mode coverage of a C++ named module (D88).
# MUST_FAIL=ON adds a module function no test calls, so gcovr must fail.
cmake_minimum_required(VERSION 3.30)
project(m0_bj LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 26)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
option(MUST_FAIL "Add the uncovered-line fixture" OFF)

# The reflection flag of the compiler (-freflection on GCC 16,
# -freflection-latest on p2996). Set, the module must build its reflection
# code, or it fails with #error.
set(REFLECTION_FLAG "" CACHE STRING "Compiler flag that enables reflection")
if(REFLECTION_FLAG)
  add_compile_options(${REFLECTION_FLAG})
  add_compile_definitions(M0_REQUIRE_REFLECTION=1)
endif()

add_compile_options(--coverage -O0)
add_link_options(--coverage)

add_library(encoder)
target_sources(encoder PUBLIC FILE_SET CXX_MODULES FILES src/encoder.cppm)
if(MUST_FAIL)
  target_sources(encoder PUBLIC FILE_SET CXX_MODULES FILES src/uncovered.cppm)
endif()

add_executable(encoder_test tests/encoder_test.cpp)
target_link_libraries(encoder_test PRIVATE encoder)

enable_testing()
add_test(NAME encoder_test COMMAND encoder_test)
