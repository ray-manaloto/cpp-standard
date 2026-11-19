# The clang23 compiler (apt clang-23) with its libc++, for the project and for
# vcpkg ports.
# Clang 23 has no reflection.
set(CMAKE_CXX_COMPILER clang++-23)
string(APPEND CMAKE_CXX_FLAGS_INIT " -stdlib=libc++")
string(APPEND CMAKE_EXE_LINKER_FLAGS_INIT " -stdlib=libc++")
string(APPEND CMAKE_SHARED_LINKER_FLAGS_INIT " -stdlib=libc++")
