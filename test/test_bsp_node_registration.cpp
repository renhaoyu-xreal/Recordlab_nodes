#include "recordlab_master/master_server.h"
#include "recordlab_nodes/deviceNodes/bsp/bsp_node.h"
#include <cassert>
#include <chrono>
#include <thread>

int main() {
  recordlab::MasterServer server(5810, 5811, 1000);
  server.start(); std::this_thread::sleep_for(std::chrono::milliseconds(100));
  recordlab::nodes::deviceNodes::bsp::BspNode node(
      std::make_unique<recordlab::nodes::SimulatedDeviceAdapter>("bsp"),
      "tcp://127.0.0.1:5810");
  assert(node.start());
  auto topics = node.client().listTopics()["data"];
  assert(topics.size() >= 4);
  assert(node.client().lookupTopic("/bsp/imu")["data"].size() == 1);
  auto actions = node.client().listActions()["data"];
  assert(actions.size() >= 6);
  node.stop(); server.stop();
}
