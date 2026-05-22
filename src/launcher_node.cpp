#include "recordlab_nodes/launcher_node.h"

#include "recordlab_master/name_resolver.h"

#include <csignal>
#include <stdexcept>
#include <thread>
#include <vector>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

namespace recordlab::nodes {

LauncherNode::LauncherNode(LauncherConfig config)
    : NodeBase("/launcher_node", "/launcher", config.master_endpoint), config_(std::move(config)) {}

LauncherNode::~LauncherNode() { stop(); }

bool LauncherNode::start() {
  if (!NodeBase::start()) return false;
  start_service_ = std::make_unique<ServiceServer>(
      [this](const json &request) { return startNode(request); });
  client_.registerService({{"node", node_name_},
                           {"service", "/launcher/start_node"},
                           {"endpoint", start_service_->endpoint()}});
  return true;
}

void LauncherNode::stop() {
  start_service_.reset();
  NodeBase::stop();
}

json LauncherNode::startNode(const json &request) {
  const std::string node = NameResolver::normalizeAbsolute(request.value("node", ""));
  if (node.empty()) throw std::runtime_error("launcher 缺少 node 参数");

  auto cmd_it = config_.nodes.find(node);
  if (cmd_it == config_.nodes.end()) {
    throw std::runtime_error("launcher 未配置该节点: " + node);
  }

  {
    std::lock_guard<std::mutex> lock(mu_);
    auto running = running_.find(node);
    if (running != running_.end()) {
      if (isProcessRunning(running->second)) {
        return {{"node", node}, {"status", "already_running"}, {"source", "launcher"},
                {"pid", running->second}};
      }
      running_.erase(running);
    }
  }

  try {
    auto nodes = client_.listNodes().value("data", json::array());
    for (const auto &item : nodes) {
      if (item.value("node", "") != node) continue;
      const std::string state = item.value("state", "");
      if (state == "alive") {
        return {{"node", node}, {"status", "already_running"}, {"source", "registry"}};
      }
      break;
    }
  } catch (...) {
  }

  const auto &argv = cmd_it->second.argv;
  pid_t pid = fork();
  if (pid < 0) throw std::runtime_error("launcher fork 失败: " + node);

  if (pid == 0) {
    std::vector<char *> args;
    args.reserve(argv.size() + 1);
    for (const auto &arg : argv) args.push_back(const_cast<char *>(arg.c_str()));
    args.push_back(nullptr);
    execvp(args[0], args.data());
    _exit(127);
  }

  {
    std::lock_guard<std::mutex> lock(mu_);
    running_[node] = pid;
  }
  std::thread(&LauncherNode::reapProcess, this, node, pid).detach();

  return {{"node", node}, {"status", "started"}, {"pid", pid}};
}

bool LauncherNode::isProcessRunning(pid_t pid) const {
  return pid > 0 && ::kill(pid, 0) == 0;
}

void LauncherNode::reapProcess(const std::string &node, pid_t pid) {
  int status = 0;
  ::waitpid(pid, &status, 0);
  std::lock_guard<std::mutex> lock(mu_);
  auto it = running_.find(node);
  if (it != running_.end() && it->second == pid) running_.erase(it);
}

}  // namespace recordlab::nodes
