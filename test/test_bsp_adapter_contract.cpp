#include "recordlab_nodes/deviceNodes/bsp/bsp_device_adapter.h"
#include <cassert>

int main() {
  recordlab::nodes::deviceNodes::bsp::BspDeviceAdapter a;
  assert(a.deviceType() == "bsp");
  assert(a.connect({})["success"]);
  assert(a.init({})["success"]);
  assert(a.start({})["success"]);
  assert(a.stop()["success"]);
}
