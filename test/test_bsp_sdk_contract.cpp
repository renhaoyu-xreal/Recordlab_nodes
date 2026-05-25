#include "recordlab_nodes/device_nodes/bsp/bsp_device_adapter.h"
#include "recordlab_xreal_runtime/xreal_sdk_probe.h"

#include <cassert>
#include <cstdlib>

int main() {
  using namespace recordlab::nodes::device_nodes::bsp;
  setenv("RECORDLAB_BSP_SDK_PROBE_JSON",
         "{\"success\":true,\"product_ids\":[1082],\"product_id\":1082,\"device_count\":1,\"fsn\":\"SDK_FSN\"}",
         1);
  auto sdk = recordlab::xreal_runtime::probeXrealSdk();
  assert(sdk["success"] == true);
  assert(sdk["product_id"] == 1082);
  assert(sdk["fsn"] == "SDK_FSN");

  setenv("RECORDLAB_LSUSB_OUTPUT", "Bus 001 Device 002: ID 3318:043a XREAL Hylla\n", 1);
  BspDeviceAdapter adapter;
  assert(adapter.connect({})["success"]);
  assert(adapter.init({})["success"]);
  assert(adapter.start({})["success"]);
  assert(adapter.initStrategy() == "hylla_bsp_sdk");
  assert(adapter.startStrategy() == "hylla_imu_slam");
  auto info = adapter.deviceInfo();
  assert(info["product_id"] == 1082);
  assert(info["fsn"] == "SDK_FSN");
  unsetenv("RECORDLAB_LSUSB_OUTPUT");
  unsetenv("RECORDLAB_BSP_SDK_PROBE_JSON");
  return 0;
}
