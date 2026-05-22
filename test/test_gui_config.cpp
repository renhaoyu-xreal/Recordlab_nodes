#include "recordlab_nodes/gui_config.h"

#include <cassert>

int main() {
  auto cfg = recordlab::nodes::loadGuiConfig(recordlab::nodes::defaultGuiConfigPath());
  assert(cfg.master_endpoint == "tcp://127.0.0.1:5590");
  assert(cfg.primary_agents.size() == 3);
  assert(cfg.primary_agents[0].node == "/bsp_node");
  assert(cfg.primary_agents[1].node == "/mcu_node");
  assert(cfg.primary_agents[2].node == "/nviz_node");
  assert(!cfg.script_roots.empty());
  return 0;
}
