# The p2996 compiler: the toolchain that `mise run toolchain:fetch` installs,
# named by its install
# prefix in CPPSTD_P2996_PREFIX. It builds against its own libc++ and finds it
# at run time through
# an rpath. Reflection is behind -freflection-latest.
if(NOT DEFINED ENV{CPPSTD_P2996_PREFIX}
   OR NOT IS_DIRECTORY "$ENV{CPPSTD_P2996_PREFIX}/bin")
  message(
    FATAL_ERROR
      "CPPSTD_P2996_PREFIX must name an installed p2996 toolchain (mise run toolchain:fetch)"
  )
endif()
set(_p2996_prefix "$ENV{CPPSTD_P2996_PREFIX}")
# vcpkg's detect_compiler enables C too, and the image has no `cc`.
set(CMAKE_C_COMPILER "${_p2996_prefix}/bin/clang")
set(CMAKE_CXX_COMPILER "${_p2996_prefix}/bin/clang++")
string(APPEND CMAKE_CXX_FLAGS_INIT
       " -std=c++26 -stdlib=libc++ -freflection-latest")
# Native Linux installations keep libc++ in the target-specific directory.
if(CMAKE_HOST_SYSTEM_PROCESSOR STREQUAL "x86_64")
  set(_p2996_runtime x86_64-unknown-linux-gnu)
else()
  set(_p2996_runtime aarch64-unknown-linux-gnu)
endif()
set(_p2996_link
    "-stdlib=libc++ -Wl,-rpath,${_p2996_prefix}/lib/${_p2996_runtime}")
string(APPEND CMAKE_EXE_LINKER_FLAGS_INIT " ${_p2996_link}")
string(APPEND CMAKE_SHARED_LINKER_FLAGS_INIT " ${_p2996_link}")
