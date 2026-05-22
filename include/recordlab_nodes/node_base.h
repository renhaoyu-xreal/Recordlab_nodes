#pragma once

#include "recordlab_master/master_client.h"

#include <atomic>
#include <map>
#include <memory>
#include <string>
#include <thread>

namespace recordlab::nodes {

class NodeBase {
 public:
  NodeBase(std::string node_name, std::string name_space = "/",
           std::string master_endpoint = "tcp://127.0.0.1:5590");
  virtual ~NodeBase();
  virtual bool start();
  virtual void stop();
  std::string name() const { return node_name_; }
  bool running() const { return running_; }
  MasterClient &client() { return client_; }

 protected:
  virtual json nodeMetadata() const;
  void heartbeatLoop();

  std::string node_name_;
  std::string namespace_;
  MasterClient client_;
  std::atomic<bool> running_{false};
  std::thread heartbeat_thread_;
};

}  // namespace recordlab::nodes
