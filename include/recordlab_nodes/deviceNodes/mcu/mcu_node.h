#pragma once

#include "recordlab_nodes/deviceNodes/mcu/mcu_device_adapter.h"
#include "recordlab_nodes/device_node_base.h"

namespace recordlab::nodes::deviceNodes::mcu {

class McuNode : public DeviceNodeBase {
 public:
  explicit McuNode(std::unique_ptr<DeviceAdapter> adapter = std::make_unique<McuDeviceAdapter>(),
                   std::string endpoint = "tcp://127.0.0.1:5590");

 protected:
  void registerInterfaces() override;
};

}  // namespace recordlab::nodes::deviceNodes::mcu
