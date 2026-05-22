#include "recordlab_master/master_server.h"
#include "recordlab_nodes/deviceNodes/mcu/mcu_node.h"
#include <cassert>
#include <chrono>
#include <thread>

int main() {
  recordlab::MasterServer server(5820, 5821, 1000);
  server.start(); std::this_thread::sleep_for(std::chrono::milliseconds(100));
  recordlab::nodes::deviceNodes::mcu::McuNode node(
      std::make_unique<recordlab::nodes::SimulatedDeviceAdapter>("mcu"),
      "tcp://127.0.0.1:5820");
  assert(node.start());
  assert(node.client().lookupTopic("/mcu/imu")["data"].size() == 1);
  assert(node.client().listActions()["data"].size() >= 6);
  node.stop(); server.stop();
}
