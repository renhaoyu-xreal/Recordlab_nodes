#pragma once

#include "recordlab_nodes/node_base.h"

#include <vector>

namespace recordlab::nodes {

class LifecycleManager : public NodeBase {
 public:
  explicit LifecycleManager(std::string endpoint = "tcp://127.0.0.1:5590");
  json planRecovery(const json &health, const json &last_state) const;
};

}  // namespace recordlab::nodes
