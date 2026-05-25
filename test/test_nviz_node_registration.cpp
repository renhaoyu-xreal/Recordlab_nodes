#include "recordlab_master/master_server.h"
#include "recordlab_nodes/device_nodes/nviz/nviz_node.h"
#include <cassert>
#include <chrono>
#include <thread>

int main() {
  recordlab::MasterServer server(5830, 5831, 1000);
  server.start(); std::this_thread::sleep_for(std::chrono::milliseconds(100));
  recordlab::nodes::device_nodes::nviz::NvizNode node(
      std::make_unique<recordlab::nodes::SimulatedDeviceAdapter>("nviz"),
      "tcp://127.0.0.1:5830");
  assert(node.start());
  assert(node.client().lookupTopic("/nviz/imu")["data"].size() == 1);
  assert(node.client().lookupTopic("/nviz/time_delay")["data"].size() == 1);
  assert(node.client().listActions()["data"].size() >= 6);
  assert(node.client().lookupAction("/nviz/start_record")["data"].empty());
  assert(node.client().lookupAction("/nviz/stop_record")["data"].empty());
  node.stop(); server.stop();
}
