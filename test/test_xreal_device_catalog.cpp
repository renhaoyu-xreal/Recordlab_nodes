#include "recordlab_xreal_runtime/xreal_device_catalog.h"

#include <cassert>

int main() {
  using namespace recordlab::xreal_runtime;
  auto catalog = loadGlassesDeviceCatalog(defaultGlassesDeviceCatalogPath());
  assert(catalog.size() >= 10);
  bool found_hylla = false;
  for (const auto &entry : catalog) {
    assert(entry.vid >= 0);
    assert(entry.pid > 0);
    assert(!entry.display_name.empty());
    assert(entry.access_mode == "bsp_sdk");
    if (entry.pid == parseUsbId("0x043a")) found_hylla = entry.display_name == "Hylla";
  }
  assert(found_hylla);
  assert(formatUsbHex(0x043a) == "0x043a");
  return 0;
}
