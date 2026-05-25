#pragma once

#include "recordlab_nodes/device_adapters.h"
#include "recordlab_core/node_base.h"
#include "recordlab_echo/echo.h"

#include <map>
#include <memory>
#include <vector>

namespace recordlab::nodes {

class DeviceNodeBase : public NodeBase {
 public:
  DeviceNodeBase(std::string node_name, std::string ns, std::unique_ptr<DeviceAdapter> adapter,
                 std::string master_endpoint = "tcp://127.0.0.1:5590");
  bool start() override;
  json callLifecycle(const std::string &op, const json &params = json::object());
  json stateMessage() const;
  LifecycleState state() const { return state_; }
  std::string health() const { return health_; }

 protected:
  json nodeMetadata() const override;
  virtual void registerInterfaces() = 0;
  void registerStateTopic(const std::string &topic);
  void registerShmTopic(const std::string &topic, const std::string &msg_type,
                        const std::string &shm_name, int slot_count, int slot_size);
  void registerLifecycle(const std::string &prefix);

  std::unique_ptr<DeviceAdapter> adapter_;
  std::unique_ptr<Publisher> state_pub_;
  std::unique_ptr<ServiceServer> check_service_;
  std::map<std::string, std::unique_ptr<ActionServer>> lifecycle_actions_;
  LifecycleState state_{LifecycleState::Disconnected};
  std::string health_{"unknown"};
  std::string message_;
};

}  // namespace recordlab::nodes
