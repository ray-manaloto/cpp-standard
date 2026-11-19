# First-party code: the code the 100% coverage rule measures.
add_library(standin)
target_sources(standin PUBLIC FILE_SET CXX_MODULES FILES standin/standin.cppm)

add_library(cppstd_core)
target_sources(cppstd_core PUBLIC FILE_SET CXX_MODULES FILES cppstd/core.cppm)
target_compile_features(cppstd_core PUBLIC cxx_std_26)
set_target_properties(cppstd_core PROPERTIES CXX_MODULE_STD ON)
