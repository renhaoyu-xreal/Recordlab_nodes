#include "recordlab_nodes/deviceNodes/bsp/bsp_node.h"
#include <cassert>

int main() {
  recordlab::nodes::deviceNodes::bsp::BspNode node(
      std::make_unique<recordlab::nodes::SimulatedDeviceAdapter>("bsp"),
      "tcp://127.0.0.1:5998");
  assert(node.callLifecycle("connect")["success"]);
  assert(node.state() == recordlab::nodes::LifecycleState::Connected);
  assert(node.callLifecycle("init")["success"]);
  assert(node.callLifecycle("start")["success"]);
  assert(node.state() == recordlab::nodes::LifecycleState::Started);
  assert(node.callLifecycle("stop")["success"]);
  assert(node.callLifecycle("release")["success"]);
  assert(node.callLifecycle("close")["success"]);
}
