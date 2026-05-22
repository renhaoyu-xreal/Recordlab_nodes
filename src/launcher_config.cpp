#include "recordlab_nodes/launcher_config.h"

#include <cstdlib>
#include <fstream>
#include <nlohmann/json.hpp>
#include <stdexcept>

namespace recordlab::nodes {
namespace {
using json = nlohmann::json;

std::string getEnvOrDefault(const char *key, const std::string &fallback) {
  const char *value = std::getenv(key);
  return (value && *value) ? std::string(value) : fallback;
}

void replaceAll(std::string &text, const std::string &from, const std::string &to) {
  if (from.empty()) return;
  std::size_t pos = 0;
  while ((pos = text.find(from, pos)) != std::string::npos) {
    text.replace(pos, from.size(), to);
    pos += to.size();
  }
}

std::string expandVars(std::string text) {
  const std::string build_dir = getEnvOrDefault("RECORDLAB_NODES_BUILD", "/home/hyren/Recordlab_nodes/build");
  replaceAll(text, "${RECORDLAB_NODES_BUILD}", build_dir);
  replaceAll(text, "$RECORDLAB_NODES_BUILD", build_dir);
  return text;
}

std::vector<std::string> parseArgv(const json &item) {
  std::vector<std::string> argv;
  if (item.is_array()) {
    for (const auto &arg : item) argv.push_back(expandVars(arg.get<std::string>()));
  } else if (item.is_string()) {
    argv.push_back(expandVars(item.get<std::string>()));
  } else if (item.is_object() && item.contains("argv")) {
    for (const auto &arg : item["argv"]) argv.push_back(expandVars(arg.get<std::string>()));
  }
  return argv;
}
}  // namespace

LauncherConfig loadLauncherConfig(const std::string &path) {
  std::ifstream in(path);
  if (!in) throw std::runtime_error("无法打开 Launcher 配置: " + path);
  json data = json::parse(in);

  LauncherConfig cfg;
  cfg.master_endpoint = data.value("master_endpoint", cfg.master_endpoint);
  if (data.contains("nodes") && data["nodes"].is_object()) {
    for (auto it = data["nodes"].begin(); it != data["nodes"].end(); ++it) {
      auto argv = parseArgv(it.value());
      if (argv.empty()) {
        throw std::runtime_error("Launcher 配置缺少 argv: " + it.key());
      }
      cfg.nodes[it.key()] = LauncherCommand{std::move(argv)};
    }
  }
  return cfg;
}

std::string defaultLauncherConfigPath() {
  return std::string(RECORDLAB_NODES_SOURCE_DIR) + "/config/recordlab_launcher.json";
}

}  // namespace recordlab::nodes
