#!/bin/bash

# Pass extra cmake options to this script, including
# things like -DCMAKE_INSTALL_PREFIX=/path/to/install, etc.

opts="$@"

cmake \
    -DCMAKE_BUILD_TYPE="Debug" \
    -DCMAKE_C_COMPILER="nvc" \
    -DCMAKE_CXX_COMPILER="nvc++" \
    -DCMAKE_C_FLAGS="-O0 -g -fPIC -pthread" \
    -DCMAKE_CXX_FLAGS="-O0 -g -fPIC -pthread -std=c++11" \
    -DOPENMP_TARGET_FLAGS="-Minfo=mp" \
    -DTOAST_STATIC_DEPS:BOOL=ON \
    -DPYTHON_EXECUTABLE:FILEPATH=$(which python3) \
    -DCMAKE_VERBOSE_MAKEFILE:BOOL=ON \
    ${opts} \
    ..
