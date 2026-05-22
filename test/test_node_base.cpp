#include "recordlab_master/master_server.h"
#include "recordlab_nodes/node_base.h"
#include <cassert>
#include <chrono>
#include <thread>

int main() {
  recordlab::MasterServer server(5800, 5801, 1000);
  server.start();
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  recordlab::nodes::NodeBase node("/unit_node", "/", "tcp://127.0.0.1:5800");
  assert(node.start());
  auto listed = node.client().listNodes();
  assert(listed["data"].size() == 1);
  node.stop();
  server.stop();
}
