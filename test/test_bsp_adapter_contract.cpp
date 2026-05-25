#include "recordlab_nodes/device_nodes/bsp/bsp_device_adapter.h"
#include <cassert>
#include <cstdlib>

int main() {
  setenv("RECORDLAB_LSUSB_OUTPUT", "Bus 001 Device 002: ID 3318:043a XREAL Hylla\n", 1);
  setenv("RECORDLAB_BSP_SDK_PROBE_JSON",
         "{\"success\":true,\"product_ids\":[1082],\"product_id\":1082,\"device_count\":1,\"fsn\":\"CONTRACT_FSN\"}",
         1);
  recordlab::nodes::device_nodes::bsp::BspDeviceAdapter a;
  assert(a.deviceType() == "bsp");
  assert(a.connect({})["success"]);
  assert(a.init({})["success"]);
  assert(a.start({})["success"]);
  assert(a.stop()["success"]);
  unsetenv("RECORDLAB_LSUSB_OUTPUT");
  unsetenv("RECORDLAB_BSP_SDK_PROBE_JSON");
}
