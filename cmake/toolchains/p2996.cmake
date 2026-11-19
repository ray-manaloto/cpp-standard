# The p2996 compiler: the toolchain that `mise run toolchain:fetch` installs,
# named by its install prefix in CPPSTD_P2996_PREFIX. It builds against its own
# libc++ and finds it at run time through an rpath. Reflection is behind
# -freflection-latest.
if(NOT DEFINED ENV{CPPSTD_P2996_PREFIX} OR NOT IS_DIRECTORY
                                           "$ENV{CPPSTD_P2996_PREFIX}/bin")
  message(
    FATAL_ERROR
      "CPPSTD_P2996_PREFIX must name an installed p2996 toolchain (mise run toolchain:fetch)"
  )
endif()
set(_p2996_prefix "$ENV{CPPSTD_P2996_PREFIX}")
set(CMAKE_CXX_COMPILER "${_p2996_prefix}/bin/clang++")
string(APPEND CMAKE_CXX_FLAGS_INIT " -stdlib=libc++ -freflection-latest")
set(_p2996_link
    "-stdlib=libc++ -Wl,-rpath,${_p2996_prefix}/lib/aarch64-unknown-linux-gnu")
string(APPEND CMAKE_EXE_LINKER_FLAGS_INIT " ${_p2996_link}")
string(APPEND CMAKE_SHARED_LINKER_FLAGS_INIT " ${_p2996_link}")
