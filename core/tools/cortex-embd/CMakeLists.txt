cmake_minimum_required(VERSION 3.16)
project(cortex_embd CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Links the already-built llama.cpp tree (build_llama.sh); LLAMA_ROOT = /opt/llama.cpp/<tag>
set(LLAMA_ROOT "/opt/llama.cpp/b12679" CACHE PATH "llama.cpp source tree")
set(LLAMA_BUILD "${LLAMA_ROOT}/build-cpu" CACHE PATH "llama.cpp CPU build tree")

add_executable(cortex-embd main.cpp)
target_include_directories(cortex-embd PRIVATE
    ${LLAMA_ROOT}/include ${LLAMA_ROOT}/ggml/include ${LLAMA_ROOT}/tools/mtmd)
target_link_directories(cortex-embd PRIVATE ${LLAMA_BUILD}/bin)
target_link_libraries(cortex-embd PRIVATE mtmd llama ggml ggml-base)
set_target_properties(cortex-embd PROPERTIES BUILD_RPATH "${LLAMA_BUILD}/bin" INSTALL_RPATH "${LLAMA_BUILD}/bin")
