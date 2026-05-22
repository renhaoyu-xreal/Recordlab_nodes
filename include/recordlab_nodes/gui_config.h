#pragma once

#include <string>
#include <vector>

namespace recordlab::nodes {

struct GuiAgentConfig {
  std::string label;
  std::string node;
};

struct GuiConfig {
  std::vector<GuiAgentConfig> primary_agents;
  std::vector<std::string> script_roots;
  std::string master_endpoint{"tcp://127.0.0.1:5590"};
};

GuiConfig loadGuiConfig(const std::string &path);
std::string defaultGuiConfigPath();

}  // namespace recordlab::nodes
