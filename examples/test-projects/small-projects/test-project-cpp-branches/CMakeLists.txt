cmake_minimum_required(VERSION 3.5)
project(test_project_cpp_branches CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(branches
    main.cpp
    if_demo.cpp
    loop_demo.cpp
    exception_demo.cpp
    single_stmt_demo.cpp
    oneline_demo.cpp
    advanced_demo.cpp
    negative_demo.cpp
    unsafe_demo.cpp
    macro_demo.cpp
    pipeline.cpp
)
