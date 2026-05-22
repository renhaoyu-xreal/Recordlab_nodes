#include "recordlab_nodes/health_monitor.h"
#include "recordlab_master/registries.h"

namespace recordlab::nodes {

HealthMonitor::HealthMonitor(std::string endpoint)
    : NodeBase("/health_monitor", "/health", std::move(endpoint)) {}

bool HealthMonitor::start() {
  if (!NodeBase::start()) return false;
  client_.registerPublisher({{"node", node_name_}, {"topic", "/health/devices"}, {"msg_type", "recordlab_msgs/Health"}, {"transport", {{"type", "tcp_pubsub"}}}});
  client_.registerPublisher({{"node", node_name_}, {"topic", "/health/topics"}, {"msg_type", "recordlab_msgs/Health"}, {"transport", {{"type", "tcp_pubsub"}}}});
  client_.registerPublisher({{"node", node_name_}, {"topic", "/health/system"}, {"msg_type", "recordlab_msgs/Health"}, {"transport", {{"type", "tcp_pubsub"}}}});
  return true;
}

json HealthMonitor::evaluateTopic(const std::string &topic, int64_t last_msg_ms, double observed_hz,
                                  double min_hz, int64_t stale_timeout_ms) const {
  const int64_t age = recordlab::nowMs() - last_msg_ms;
  if (age > stale_timeout_ms) return json{{"topic", topic}, {"health", "stale"}, {"age_ms", age}};
  if (observed_hz < min_hz) return {{"topic", topic}, {"health", "low_rate"}, {"hz", observed_hz}};
  return {{"topic", topic}, {"health", "ok"}, {"hz", observed_hz}};
}

}  // namespace recordlab::nodes
