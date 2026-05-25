#include "recordlab_nodes/device_nodes/mcu/mcu_device_adapter.h"
#include <cassert>

int main() {
  recordlab::nodes::device_nodes::mcu::McuDeviceAdapter a;
  assert(a.deviceType() == "mcu");
  assert(a.connect({})["success"]);
  assert(a.init({})["success"]);
  assert(a.start({})["success"]);
}
