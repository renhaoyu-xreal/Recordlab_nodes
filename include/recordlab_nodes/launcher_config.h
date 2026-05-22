#pragma once

#include <map>
#include <string>
#include <vector>

namespace recordlab::nodes {

struct LauncherCommand {
  std::vector<std::string> argv;
};

struct LauncherConfig {
  std::string master_endpoint = "tcp://127.0.0.1:5590";
  std::map<std::string, LauncherCommand> nodes;
};

LauncherConfig loadLauncherConfig(const std::string &path);
std::string defaultLauncherConfigPath();

}  // namespace recordlab::nodes
