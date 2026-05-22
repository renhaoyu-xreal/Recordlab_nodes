#include "recordlab_nodes/node_base.h"

#include <chrono>

namespace recordlab::nodes {

NodeBase::NodeBase(std::string node_name, std::string name_space, std::string master_endpoint)
    : node_name_(std::move(node_name)), namespace_(std::move(name_space)), client_(std::move(master_endpoint)) {}

NodeBase::~NodeBase() { stop(); }

json NodeBase::nodeMetadata() const {
  return {{"node", node_name_}, {"namespace", namespace_}, {"kind", "node"}};
}

bool NodeBase::start() {
  if (running_.exchange(true)) return true;
  auto resp = client_.registerNode(nodeMetadata());
  if (!resp.value("ok", false)) {
    running_ = false;
    return false;
  }
  heartbeat_thread_ = std::thread(&NodeBase::heartbeatLoop, this);
  return true;
}

void NodeBase::stop() {
  if (!running_.exchange(false)) return;
  try { client_.unregisterNode(node_name_); } catch (...) {}
  if (heartbeat_thread_.joinable()) heartbeat_thread_.join();
}

void NodeBase::heartbeatLoop() {
  while (running_) {
    try { client_.heartbeat(node_name_); } catch (...) {}
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
  }
}

}  // namespace recordlab::nodes
