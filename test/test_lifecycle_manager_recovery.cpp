#include "recordlab_nodes/lifecycle_manager.h"
#include <cassert>

int main() {
  recordlab::nodes::LifecycleManager lm("tcp://127.0.0.1:5998");
  auto p = lm.planRecovery({{"health", "stale"}}, {{"lifecycle_state", "started"}});
  assert(p["actions"].size() == 3);
  auto rec = lm.planRecovery({{"health", "error"}}, {{"lifecycle_state", "recording"}});
  assert(rec.value("critical", false));
}
