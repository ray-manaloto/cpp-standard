add_executable(standin_test standin_test.cpp)
target_link_libraries(standin_test PRIVATE standin)
add_test(NAME standin_test COMMAND standin_test)
