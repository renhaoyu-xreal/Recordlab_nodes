#include "recordlab_nodes/deviceNodes/mcu/mcu_device_adapter.h"
#include <cassert>

int main() {
  recordlab::nodes::deviceNodes::mcu::McuDeviceAdapter a;
  assert(a.deviceType() == "mcu");
  assert(a.connect({})["success"]);
  assert(a.init({})["success"]);
  assert(a.start({})["success"]);
}
