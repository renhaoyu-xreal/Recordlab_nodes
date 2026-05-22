#pragma once

#include "recordlab_nodes/launcher_config.h"
#include "recordlab_nodes/node_base.h"
#include "recordlab_master/transport.h"

#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <sys/types.h>

namespace recordlab::nodes {

class LauncherNode : public NodeBase {
 public:
  explicit LauncherNode(LauncherConfig config);
  ~LauncherNode() override;

  bool start() override;
  void stop() override;

 private:
  json startNode(const json &request);
  bool isProcessRunning(pid_t pid) const;
  void reapProcess(const std::string &node, pid_t pid);

  LauncherConfig config_;
  std::unique_ptr<ServiceServer> start_service_;
  std::mutex mu_;
  std::map<std::string, pid_t> running_;
};

}  // namespace recordlab::nodes
