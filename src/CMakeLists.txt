# First-party code: the code the 100% coverage rule measures.
add_library(standin)
target_sources(standin PUBLIC FILE_SET CXX_MODULES FILES standin/standin.cppm)
