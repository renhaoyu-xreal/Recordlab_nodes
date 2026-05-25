#include "recordlab_nodes/device_nodes/nviz/nviz_device_adapter.h"
#include <cassert>

int main() {
  recordlab::nodes::device_nodes::nviz::NvizDeviceAdapter a;
  assert(a.deviceType() == "nviz");
  assert(a.connect({})["success"]);
  assert(a.init({})["success"]);
  assert(a.start({})["success"]);
  assert(a.release()["success"]);
}
