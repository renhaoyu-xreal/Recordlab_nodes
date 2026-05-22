#pragma once

#include "recordlab_nodes/node_base.h"

#include <map>

namespace recordlab::nodes {

class HealthMonitor : public NodeBase {
 public:
  explicit HealthMonitor(std::string endpoint = "tcp://127.0.0.1:5590");
  bool start() override;
  json evaluateTopic(const std::string &topic, int64_t last_msg_ms, double observed_hz,
                     double min_hz, int64_t stale_timeout_ms) const;
};

}  // namespace recordlab::nodes
