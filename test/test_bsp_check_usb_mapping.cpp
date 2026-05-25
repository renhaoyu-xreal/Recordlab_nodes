#include "recordlab_nodes/device_nodes/bsp/bsp_device_adapter.h"
#include "recordlab_xreal_runtime/xreal_device_catalog.h"

#include <cassert>
#include <cstdlib>

int main() {
  using namespace recordlab::nodes::device_nodes::bsp;
  auto catalog = recordlab::xreal_runtime::loadGlassesDeviceCatalog(
      recordlab::xreal_runtime::defaultGlassesDeviceCatalogPath());
  auto detected = recordlab::xreal_runtime::detectGlassesUsbDevicesFromLsusb(
      catalog, "Bus 001 Device 002: ID 3318:043a XREAL Hylla\n");
  assert(detected.size() == 1);
  assert(detected.front().catalog.display_name == "Hylla");

  setenv("RECORDLAB_LSUSB_OUTPUT", "Bus 001 Device 002: ID 3318:043a XREAL Hylla\n", 1);
  setenv("RECORDLAB_BSP_SDK_PROBE_JSON",
         "{\"success\":true,\"product_ids\":[1082],\"product_id\":1082,\"device_count\":1,\"fsn\":\"FSN_TEST\"}",
         1);
  BspDeviceAdapter adapter;
  auto result = adapter.check();
  assert(result["success"] == true);
  assert(result["device_info"]["catalog_name"] == "Hylla");
  assert(result["device_info"]["product_id"] == 1082);
  assert(result["device_info"]["fsn"] == "FSN_TEST");
  unsetenv("RECORDLAB_LSUSB_OUTPUT");
  unsetenv("RECORDLAB_BSP_SDK_PROBE_JSON");
  return 0;
}
