#include "recordlab_nodes/deviceNodes/nviz/nviz_device_adapter.h"
#include <cassert>

int main() {
  recordlab::nodes::deviceNodes::nviz::NvizDeviceAdapter a;
  assert(a.deviceType() == "nviz");
  assert(a.connect({})["success"]);
  assert(a.init({})["success"]);
  assert(a.start({})["success"]);
  assert(a.release()["success"]);
}
