cmake_minimum_required(VERSION 3.20)
project(CoreFlux VERSION 0.1 LANGUAGES CXX)
find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBBPF REQUIRED IMPORTED_TARGET libbpf)
find_program(CLANG_EXECUTABLE clang REQUIRED)
find_program(PYTHON_EXECUTABLE python3 REQUIRED)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_executable(coreflux-agent agent/main.cpp)
target_include_directories(coreflux-agent PRIVATE include)
target_compile_options(coreflux-agent PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(coreflux-workload workloads/main.cpp)
add_executable(coreflux-ring-reader agent/ring_reader.cpp)
target_include_directories(coreflux-ring-reader PRIVATE include)
target_compile_options(coreflux-ring-reader PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(coreflux-ebpf-loader ebpf/loader.cpp)
add_executable(coreflux-analyze agent/analyze.cpp agent/scorer.cpp)
add_executable(coreflux-policy agent/policy.cpp)
target_compile_options(coreflux-policy PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_include_directories(coreflux-analyze PRIVATE include)
target_compile_options(coreflux-analyze PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_include_directories(coreflux-ebpf-loader PRIVATE include)
target_link_libraries(coreflux-ebpf-loader PRIVATE PkgConfig::LIBBPF)
target_compile_options(coreflux-ebpf-loader PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_custom_command(OUTPUT ${CMAKE_BINARY_DIR}/sched.bpf.o
    COMMAND ${CLANG_EXECUTABLE} -O2 -g -target bpf -I${CMAKE_SOURCE_DIR}/include
        -I/usr/include/x86_64-linux-gnu -c ${CMAKE_SOURCE_DIR}/ebpf/sched.bpf.c
        -o ${CMAKE_BINARY_DIR}/sched.bpf.o
    DEPENDS ebpf/sched.bpf.c include/coreflux/uapi.h)
add_custom_target(coreflux-ebpf-object ALL DEPENDS ${CMAKE_BINARY_DIR}/sched.bpf.o)
target_compile_options(coreflux-workload PRIVATE -Wall -Wextra -Wpedantic -Werror)
enable_testing()
add_test(NAME agent_smoke COMMAND coreflux-agent --synthetic --output ${CMAKE_BINARY_DIR}/agent-smoke.jsonl)
add_test(NAME workload_smoke COMMAND coreflux-workload --mode cpu --seconds 1 --threads 1)
add_test(NAME latency_smoke COMMAND coreflux-workload --mode latency --seconds 1 --threads 1)
add_test(NAME scoring_replay COMMAND coreflux-analyze
    ${CMAKE_SOURCE_DIR}/tests/agent/contention-replay.csv ${CMAKE_BINARY_DIR}/scoring-replay.jsonl)
add_test(NAME scoring_behavior COMMAND ${PYTHON_EXECUTABLE}
    ${CMAKE_SOURCE_DIR}/tests/agent/test_scorer.py $<TARGET_FILE:coreflux-analyze>)
add_test(NAME perf_parser COMMAND ${PYTHON_EXECUTABLE}
    ${CMAKE_SOURCE_DIR}/tests/agent/test_performance_suite.py)
add_test(NAME perf_analysis COMMAND ${PYTHON_EXECUTABLE}
    ${CMAKE_SOURCE_DIR}/tests/agent/test_performance_analysis.py)
add_test(NAME memory_handshake COMMAND ${PYTHON_EXECUTABLE}
    ${CMAKE_SOURCE_DIR}/tests/agent/test_memory_handshake.py $<TARGET_FILE:coreflux-workload>)
add_test(NAME backend_summary COMMAND ${PYTHON_EXECUTABLE}
    ${CMAKE_SOURCE_DIR}/tests/agent/test_backend_summary.py)
add_executable(coreflux-latency-histogram-test tests/agent/test_latency_histogram.cpp)
target_include_directories(coreflux-latency-histogram-test PRIVATE include)
target_compile_options(coreflux-latency-histogram-test PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME latency_histogram COMMAND coreflux-latency-histogram-test)
