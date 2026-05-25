cmake_minimum_required(VERSION 3.16)
project(Recordlab_nodes CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED RECORDLAB_MASTER_DIR)
  if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/third_party/Recordlab_master/CMakeLists.txt")
    set(RECORDLAB_MASTER_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/Recordlab_master")
  else()
    set(RECORDLAB_MASTER_DIR "/home/hyren/Recordlab_master")
  endif()
endif()

set(BUILD_RECORDLAB_MASTER_TOOLS OFF CACHE BOOL "" FORCE)
set(BUILD_RECORDLAB_MASTER_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory(${RECORDLAB_MASTER_DIR} ${CMAKE_BINARY_DIR}/recordlab_master_build)

add_library(recordlab_nodes
  src/device_node_base.cpp
  src/device_adapters.cpp
  src/device_nodes/bsp/bsp_device_adapter.cpp
  src/device_nodes/bsp/bsp_node.cpp
  src/device_nodes/mcu/mcu_device_adapter.cpp
  src/device_nodes/mcu/mcu_node.cpp
  src/device_nodes/nviz/nviz_device_adapter.cpp
  src/device_nodes/nviz/nviz_node.cpp
)
target_include_directories(recordlab_nodes PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_link_libraries(recordlab_nodes PUBLIC recordlab_master recordlab_xreal_runtime)
target_compile_definitions(recordlab_nodes PUBLIC
  RECORDLAB_NODES_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
)

foreach(bin bsp_node mcu_node nviz_node)
  add_executable(${bin} tools/${bin}.cpp)
  target_link_libraries(${bin} PRIVATE recordlab_nodes)
endforeach()

enable_testing()
foreach(t
  test_device_lifecycle
  test_bsp_node_registration
  test_mcu_node_registration
  test_nviz_node_registration
  test_bsp_adapter_contract
  test_mcu_adapter_contract
  test_nviz_adapter_contract
  test_xreal_device_catalog
  test_bsp_check_usb_mapping
  test_bsp_sdk_contract
  test_xreal_runtime_bridge
  test_record_bsp_imu_cam_script
  test_record_nviz_ur_gt_3dof_batch_script
)
  add_executable(${t} test/${t}.cpp)
  target_link_libraries(${t} PRIVATE recordlab_nodes)
  if(t MATCHES "test_record_(bsp_imu_cam|nviz_ur_gt_3dof_batch)_script")
    target_link_libraries(${t} PRIVATE recordlab_system_nodes)
  endif()
  add_test(NAME ${t} COMMAND ${t})
endforeach()
