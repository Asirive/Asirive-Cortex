cmake_minimum_required(VERSION 3.16)
project(cortex_engine CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Links the already-built llama.cpp tree; LLAMA_ROOT = /opt/llama.cpp/<tag>. QNN_INCLUDE = QAIRT include/QNN
# (2.42.0, outside git). The NPU shim source (../cortex-npu/cortex_npu.cpp) is compiled into the library.
set(LLAMA_ROOT "/opt/llama.cpp/b12679" CACHE PATH "llama.cpp source tree")
set(LLAMA_BUILD "${LLAMA_ROOT}/build-cpu" CACHE PATH "llama.cpp CPU build tree")
set(QNN_INCLUDE "$ENV{HOME}/qnn-inc/QNN" CACHE PATH "QNN headers")

set(ENGINE_SRC src/fixed.cpp src/island.cpp src/vision.cpp src/prep.cpp src/lm.cpp src/engine.cpp ../cortex-npu/cortex_npu.cpp)

add_library(cortex_engine SHARED ${ENGINE_SRC})
target_include_directories(cortex_engine PUBLIC
    include src ${LLAMA_ROOT}/include ${LLAMA_ROOT}/ggml/include ${LLAMA_ROOT}/tools/mtmd ${LLAMA_ROOT}/vendor
    ${QNN_INCLUDE})
target_compile_options(cortex_engine PRIVATE -Wall -O2)
target_link_directories(cortex_engine PUBLIC ${LLAMA_BUILD}/bin)
target_link_libraries(cortex_engine PUBLIC mtmd llama ggml ggml-base ggml-cpu dl pthread)
set_target_properties(cortex_engine PROPERTIES BUILD_RPATH "${LLAMA_BUILD}/bin" INSTALL_RPATH "${LLAMA_BUILD}/bin")

file(GLOB TEST_SRC CONFIGURE_DEPENDS tests/*.cpp)
add_executable(engine_tests ${TEST_SRC})
target_link_libraries(engine_tests PRIVATE cortex_engine)
set_target_properties(engine_tests PROPERTIES BUILD_RPATH "${LLAMA_BUILD}/bin;${CMAKE_BINARY_DIR}")

add_executable(cortex-engine src/cli.cpp)
target_link_libraries(cortex-engine PRIVATE cortex_engine)
set_target_properties(cortex-engine PROPERTIES BUILD_RPATH "${LLAMA_BUILD}/bin;${CMAKE_BINARY_DIR}")
