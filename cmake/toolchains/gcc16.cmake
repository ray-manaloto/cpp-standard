# The gcc16 compiler for the project and for vcpkg ports (the triplet chainloads
# this file). GCC 16 has reflection behind -freflection. Flags go in _INIT so a
# preset's CXXFLAGS environment adds to them instead of replacing them.
set(CMAKE_CXX_COMPILER g++-16)
string(APPEND CMAKE_CXX_FLAGS_INIT " -freflection")
