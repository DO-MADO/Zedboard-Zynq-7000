cmake_minimum_required(VERSION 3.15)
# Require at least CMake 3.15

project(zedBoard)
# Project name is "zedBoard"

set(CMAKE_C_STANDARD 11)
# Use C11 standard for C language

add_executable(zedBoard main.c)
# Compile main.c into an executable named "zedBoard"

add_executable(iio_reader iio_reader.c)

add_executable(iio_reader_test iio_reader_test.c)

# ===================== [libiio linking] =====================

include_directories(${CMAKE_SOURCE_DIR}/libiio/include)

# Add include path for libiio (so that #include <iio.h> works)

link_directories(${CMAKE_SOURCE_DIR}/libiio/lib)
# Add library search path for libiio (.lib files)

target_link_libraries(zedBoard ${CMAKE_SOURCE_DIR}/libiio/lib/libiio.lib)
# Link the executable with libiio.lib

target_link_libraries(iio_reader ${CMAKE_SOURCE_DIR}/libiio/lib/libiio.lib)

target_link_libraries(iio_reader_test ${CMAKE_SOURCE_DIR}/libiio/lib/libiio.lib)
