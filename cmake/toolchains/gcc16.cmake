# The gcc16 compiler for the project and for vcpkg ports (the triplet chainloads
# this file). GCC 16
# has reflection behind -freflection. Flags go in _INIT so a preset's CXXFLAGS
# environment adds to
# them instead of replacing them.
# vcpkg's detect_compiler enables C too, and the image has no `cc`.
set(CMAKE_C_COMPILER gcc-16)
set(CMAKE_CXX_COMPILER g++-16)
# -freflection needs -std=c++26 on the command line, which vcpkg's compiler
# detection and the ports
# build without (the project sets CMAKE_CXX_STANDARD itself).
string(APPEND CMAKE_CXX_FLAGS_INIT " -std=c++26 -freflection")
