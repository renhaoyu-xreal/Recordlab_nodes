#include "recordlab_nodes/lifecycle_manager.h"

namespace recordlab::nodes {

LifecycleManager::LifecycleManager(std::string endpoint)
    : NodeBase("/lifecycle_manager", "/lifecycle", std::move(endpoint)) {}

json LifecycleManager::planRecovery(const json &health, const json &last_state) const {
  if (health.value("health", "ok") == "ok") return {{"actions", json::array()}, {"reason", "healthy"}};
  if (last_state.value("lifecycle_state", "") == "recording") {
    return {{"actions", json::array()}, {"critical", true}, {"reason", "recording; do not auto-resume dataset"}};
  }
  json actions = json::array({"connect", "init"});
  if (last_state.value("lifecycle_state", "") == "started") actions.push_back("start");
  return {{"actions", actions}, {"reason", "auto recovery policy"}};
}

}  // namespace recordlab::nodes
