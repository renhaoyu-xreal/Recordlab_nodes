#include "recordlab_nodes/gui_config.h"

#include <fstream>
#include <nlohmann/json.hpp>
#include <stdexcept>

namespace recordlab::nodes {
namespace {
using json = nlohmann::json;
}

GuiConfig loadGuiConfig(const std::string &path) {
  std::ifstream in(path);
  if (!in) throw std::runtime_error("无法打开 GUI 配置: " + path);
  json data = json::parse(in);
  GuiConfig cfg;
  cfg.master_endpoint = data.value("master_endpoint", cfg.master_endpoint);
  if (data.contains("primary_agents")) {
    for (const auto &item : data["primary_agents"]) {
      cfg.primary_agents.push_back({item.value("label", item.value("node", "")),
                                    item.value("node", "")});
    }
  }
  if (data.contains("script_roots")) {
    for (const auto &item : data["script_roots"]) cfg.script_roots.push_back(item.get<std::string>());
  }
  return cfg;
}

std::string defaultGuiConfigPath() {
  return std::string(RECORDLAB_NODES_SOURCE_DIR) + "/config/recordlab_gui.json";
}

}  // namespace recordlab::nodes
