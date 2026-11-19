# The clang23 compiler (apt clang-23) with its libc++, for the project and for
# vcpkg ports.
# Clang 23 has no reflection.
# vcpkg's detect_compiler enables C too, and the image has no `cc`.
set(CMAKE_C_COMPILER clang-23)
set(CMAKE_CXX_COMPILER clang++-23)
string(APPEND CMAKE_CXX_FLAGS_INIT " -stdlib=libc++")
string(APPEND CMAKE_EXE_LINKER_FLAGS_INIT " -stdlib=libc++")
string(APPEND CMAKE_SHARED_LINKER_FLAGS_INIT " -stdlib=libc++")

# CMake 4.5 picked libstdc++'s module manifest (std.cc under
# /usr/include/c++/16) for this compiler
# in the gate, so `import std` scanned the wrong source. Name libc++'s manifest
# as the compiler
# reports it for -stdlib=libc++.
execute_process(
  COMMAND clang++-23 -stdlib=libc++ -print-file-name=libc++.modules.json
  OUTPUT_VARIABLE _clang23_modules_json OUTPUT_STRIP_TRAILING_WHITESPACE)
if(NOT EXISTS "${_clang23_modules_json}")
  message(
    FATAL_ERROR
      "clang++-23 finds no libc++.modules.json: ${_clang23_modules_json}")
endif()
set(CMAKE_CXX_STDLIB_MODULES_JSON "${_clang23_modules_json}")
