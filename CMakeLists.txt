cmake_minimum_required(VERSION 3.16)
project(Recordlab_nodes CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

find_package(Qt6 6.2 REQUIRED COMPONENTS Core Gui Widgets)

if(NOT DEFINED RECORDLAB_MASTER_DIR)
  set(RECORDLAB_MASTER_DIR "/home/hyren/Recordlab_master")
endif()

set(BUILD_RECORDLAB_MASTER_TOOLS OFF CACHE BOOL "" FORCE)
set(BUILD_RECORDLAB_MASTER_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory(${RECORDLAB_MASTER_DIR} ${CMAKE_BINARY_DIR}/recordlab_master_build)

add_library(recordlab_nodes
  src/node_base.cpp
  src/device_node_base.cpp
  src/device_adapters.cpp
  src/launcher_config.cpp
  src/launcher_node.cpp
  src/deviceNodes/bsp/bsp_device_adapter.cpp
  src/deviceNodes/bsp/bsp_node.cpp
  src/deviceNodes/mcu/mcu_device_adapter.cpp
  src/deviceNodes/mcu/mcu_node.cpp
  src/deviceNodes/nviz/nviz_device_adapter.cpp
  src/deviceNodes/nviz/nviz_node.cpp
  src/gui_config.cpp
  src/health_monitor.cpp
  src/lifecycle_manager.cpp
  src/watchdog_node.cpp
)
target_include_directories(recordlab_nodes PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_link_libraries(recordlab_nodes PUBLIC recordlab_master)
target_compile_definitions(recordlab_nodes PUBLIC
  RECORDLAB_NODES_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
)

foreach(bin bsp_node mcu_node nviz_node health_monitor lifecycle_manager recorder_node watchdog_node)
  add_executable(${bin} tools/${bin}.cpp)
  target_link_libraries(${bin} PRIVATE recordlab_nodes)
endforeach()

add_executable(recordlab_gui tools/recordlab_gui.cpp)
target_link_libraries(recordlab_gui PRIVATE recordlab_nodes Qt6::Core Qt6::Gui Qt6::Widgets)

add_executable(recordlab_launcher tools/recordlab_launcher.cpp)
target_link_libraries(recordlab_launcher PRIVATE recordlab_nodes)

enable_testing()
foreach(t
  test_node_base
  test_device_lifecycle
  test_health_monitor
  test_lifecycle_manager_recovery
  test_bsp_node_registration
  test_mcu_node_registration
  test_nviz_node_registration
  test_bsp_adapter_contract
  test_mcu_adapter_contract
  test_nviz_adapter_contract
  test_watchdog_node
  test_gui_config
)
  add_executable(${t} test/${t}.cpp)
  target_link_libraries(${t} PRIVATE recordlab_nodes)
  add_test(NAME ${t} COMMAND ${t})
endforeach()
