#include "recordlab_nodes/watchdog_node.h"

#include "recordlab_master/name_resolver.h"
#include "recordlab_master/registries.h"

#include <chrono>

namespace recordlab::nodes {

WatchdogNode::WatchdogNode(std::string endpoint)
    : NodeBase("/watchdog_node", "/watchdog", std::move(endpoint)) {}

WatchdogNode::~WatchdogNode() { stop(); }

bool WatchdogNode::start() {
  if (!NodeBase::start()) return false;

  state_pub_ = std::make_unique<Publisher>("/watchdog/state");
  set_target_service_ = std::make_unique<ServiceServer>(
      [this](const json &request) { return setTarget(request); });
  clear_target_service_ = std::make_unique<ServiceServer>(
      [this](const json &request) { return clearTarget(request); });

  client_.registerPublisher({{"node", node_name_},
                             {"topic", "/watchdog/state"},
                             {"msg_type", "recordlab_msgs/WatchdogState"},
                             {"transport", {{"type", "tcp_pubsub"},
                                             {"endpoint", state_pub_->endpoint()}}}});
  client_.registerService({{"node", node_name_},
                           {"service", "/watchdog/set_target"},
                           {"endpoint", set_target_service_->endpoint()}});
  client_.registerService({{"node", node_name_},
                           {"service", "/watchdog/clear_target"},
                           {"endpoint", clear_target_service_->endpoint()}});

  monitor_running_ = true;
  monitor_thread_ = std::thread(&WatchdogNode::loop, this);
  publishState({{"target", ""}, {"health", "idle"}, {"message", "未选择主 agent"},
                {"timestamp_ms", nowMs()}});
  return true;
}

void WatchdogNode::stop() {
  monitor_running_ = false;
  if (monitor_thread_.joinable()) monitor_thread_.join();
  clear_target_service_.reset();
  set_target_service_.reset();
  state_pub_.reset();
  NodeBase::stop();
}

json WatchdogNode::evaluateTarget(const json &nodes, const std::string &target) const {
  if (target.empty()) {
    return {{"target", ""}, {"health", "idle"}, {"message", "未选择主 agent"},
            {"timestamp_ms", nowMs()}};
  }
  for (const auto &node : nodes) {
    if (node.value("node", "") != target) continue;
    const std::string state = node.value("state", "offline");
    if (state == "alive") {
      return {{"target", target}, {"health", "ok"}, {"message", "主 agent 在线"},
              {"timestamp_ms", nowMs()}};
    }
    if (state == "stale") {
      return {{"target", target}, {"health", "stale"}, {"message", "主 agent 心跳超时"},
              {"timestamp_ms", nowMs()}};
    }
    return {{"target", target}, {"health", "error"}, {"message", "主 agent 状态异常: " + state},
            {"timestamp_ms", nowMs()}};
  }
  return {{"target", target}, {"health", "offline"}, {"message", "主 agent 未注册"},
          {"timestamp_ms", nowMs()}};
}

std::string WatchdogNode::target() const {
  std::lock_guard<std::mutex> lock(target_mu_);
  return target_;
}

json WatchdogNode::setTarget(const json &request) {
  const std::string node = NameResolver::normalizeAbsolute(request.value("node", ""));
  {
    std::lock_guard<std::mutex> lock(target_mu_);
    target_ = node;
  }
  auto state = evaluateTarget(client_.listNodes().value("data", json::array()), node);
  publishState(state);
  return {{"target", node}, {"state", state}};
}

json WatchdogNode::clearTarget(const json &) {
  {
    std::lock_guard<std::mutex> lock(target_mu_);
    target_.clear();
  }
  json state = {{"target", ""}, {"health", "idle"}, {"message", "未选择主 agent"},
                {"timestamp_ms", nowMs()}};
  publishState(state);
  return state;
}

void WatchdogNode::loop() {
  while (monitor_running_) {
    try {
      auto nodes = client_.listNodes().value("data", json::array());
      publishState(evaluateTarget(nodes, target()));
    } catch (...) {
      publishState({{"target", target()}, {"health", "error"}, {"message", "无法查询 Master"},
                    {"timestamp_ms", nowMs()}});
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
  }
}

void WatchdogNode::publishState(const json &state) {
  if (state_pub_) state_pub_->publish(state);
}

}  // namespace recordlab::nodes
