#include "recordlab_nodes/node_base.h"
#include <chrono>
#include <iostream>
#include <thread>
int main() {
  recordlab::nodes::NodeBase node("/recorder_node", "/record");
  if (!node.start()) return 1;
  node.client().registerPublisher({{"node", "/recorder_node"}, {"topic", "/record/status"}, {"msg_type", "recordlab_msgs/RecordStatus"}, {"transport", {{"type", "tcp_pubsub"}}}});
  std::cout << "recorder_node running\n";
  while (true) std::this_thread::sleep_for(std::chrono::seconds(1));
}
