cmake_minimum_required(VERSION 3.10)
project(TestProject)

set(CMAKE_CXX_STANDARD 14)

add_executable(test-project
    main.cpp
    utils.cpp
    classes.cpp
    calculator.cpp
    string_processor.cpp
    counter.cpp
    qt_example.cpp
    file_storage.cpp
    unsafe_demo.cpp
)
