find_package(ut CONFIG REQUIRED)

add_executable(standin_test standin_test.cpp)
target_link_libraries(standin_test PRIVATE standin)
add_test(NAME standin_test COMMAND standin_test)

add_executable(core_test core_test.cpp)
target_link_libraries(core_test PRIVATE cppstd_core Boost::ut)
set_target_properties(core_test PROPERTIES CXX_MODULE_STD ON)
add_test(NAME core_test COMMAND core_test)
